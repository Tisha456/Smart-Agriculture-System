"""Drive <-> local disk I/O: mounting, archive transfer, and atomic
checkpoint sync. See plant-disease-implementation-plan.md section 1.1 —
Drive is durable/cold storage, /content is the fast, disposable working
disk. Nothing here should ever leave a partially-written file where a
later reader could mistake it for complete (this is what makes training
survive a Colab disconnect).
"""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from .config import PATHS
from .logging_utils import get_logger

log = get_logger("drive_io")


def is_colab() -> bool:
    return "COLAB_GPU" in os.environ or Path("/content").exists()


def mount() -> None:
    """Mount Google Drive. No-op if already mounted. Hard error off Colab.

    Checks os.path.ismount(), NOT just whether MyDrive/ exists as a
    directory — a plain-directory check is a real trap: if anything ever
    calls mkdir(parents=True) on a path under /content/drive before Drive
    is actually mounted (e.g. config.ensure_dirs() running before this),
    that creates ordinary local folders that look identical to a mount
    from the outside. A directory-existence check would then report
    "already mounted" forever after, silently sending every subsequent
    archive/checkpoint to ephemeral local storage instead of Drive.
    """
    mount_point = Path("/content/drive")
    if os.path.ismount(mount_point):
        log.info("Drive already mounted.")
        return

    if not is_colab():
        if "AGRISENSE_PD_DRIVE_ROOT" in os.environ:
            PATHS.drive_root.mkdir(parents=True, exist_ok=True)
            log.info("Not on Colab — using %s as durable storage (no mount needed).", PATHS.drive_root)
            return
        raise RuntimeError(
            "drive_io.mount() called off Colab. Set AGRISENSE_PD_DRIVE_ROOT to "
            "a local directory instead for non-Colab development/testing."
        )

    from google.colab import drive  # type: ignore

    drive.mount(str(mount_point))
    if not os.path.ismount(mount_point):
        raise RuntimeError(
            "Drive mount reported success but /content/drive is not a real mount point. "
            "Do not proceed — anything written under it will be lost when this runtime ends."
        )
    log.info("Drive mounted at %s", mount_point)


def _human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}PB"


def pull_archive(name: str, dest_dir: Path | None = None) -> Path:
    """Copy an archive from Drive archives/ to local disk (verifying size),
    returning the local path. Skips the copy if an identically-sized file
    already exists locally.
    """
    src = PATHS.archives / name
    if not src.exists():
        raise FileNotFoundError(
            f"Archive {name} not found in {PATHS.archives}. "
            "Run download.py first, or place the file there manually."
        )
    dest_dir = dest_dir or (PATHS.local_root / "_archives_tmp")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / name

    src_size = src.stat().st_size
    if dest.exists() and dest.stat().st_size == src_size:
        log.info("%s already present locally and matches size, skipping copy.", name)
        return dest

    log.info("Copying %s (%s) from Drive to local disk...", name, _human_size(src_size))
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(src, tmp)
    if tmp.stat().st_size != src_size:
        tmp.unlink(missing_ok=True)
        raise IOError(f"Size mismatch copying {name}: expected {src_size}, got {tmp.stat().st_size}")
    tmp.rename(dest)
    log.info("Copied %s to %s", name, dest)
    return dest


def push_archive(local_path: Path, name: str | None = None) -> Path:
    """Copy a local archive up to Drive archives/, atomically."""
    name = name or local_path.name
    PATHS.archives.mkdir(parents=True, exist_ok=True)
    dest = PATHS.archives / name
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    shutil.copyfile(local_path, tmp)
    src_size = local_path.stat().st_size
    if tmp.stat().st_size != src_size:
        tmp.unlink(missing_ok=True)
        raise IOError(f"Size mismatch pushing {name} to Drive")
    tmp.rename(dest)
    log.info("Pushed %s to Drive at %s", name, dest)
    return dest


def sync_checkpoint(src: Path, dest_subdir: Path) -> Path:
    """Copy a checkpoint file to Drive atomically: write to a temp file in
    the destination directory, then os.replace (atomic on POSIX and NTFS
    within the same filesystem) so a disconnect mid-copy never leaves a
    corrupt/truncated checkpoint sitting at the final path.
    """
    src = Path(src)
    if not src.exists():
        raise FileNotFoundError(f"Checkpoint source does not exist: {src}")
    dest_subdir = Path(dest_subdir)
    dest_subdir.mkdir(parents=True, exist_ok=True)
    dest = dest_subdir / src.name

    fd, tmp_name = tempfile.mkstemp(dir=str(dest_subdir), prefix=".tmp_", suffix=src.suffix)
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp_path)
        os.replace(tmp_path, dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    log.info("Synced checkpoint %s -> %s", src, dest)
    return dest


def pull_checkpoint(drive_path: Path, dest: Path) -> Path | None:
    """Pull a checkpoint from Drive to local disk if it exists. Returns
    None (not an error) if there is nothing to resume from yet.
    """
    drive_path = Path(drive_path)
    if not drive_path.exists():
        return None
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(drive_path, dest)
    log.info("Pulled checkpoint %s -> %s", drive_path, dest)
    return dest
