"""Phase A2 — acquire the three raw datasets.

Order per dataset: archive already in Drive archives/ -> skip download ->
copy to /content -> extract -> verify -> delete the LOCAL archive copy
(never the Drive one, so re-running never re-downloads).

Usage:
    python -m agrisense_pd.data.download                 # all three
    python -m agrisense_pd.data.download --only plantdoc  # just one
    python -m agrisense_pd.data.download --force          # re-download all
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import yaml

from .. import drive_io
from ..config import CONFIGS_DIR, PATHS
from ..logging_utils import get_logger

log = get_logger("download")


def _load_sources() -> dict:
    with open(CONFIGS_DIR / "sources.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _check_kaggle_credentials() -> None:
    kaggle_json = Path.home() / ".kaggle" / "kaggle.json"
    if kaggle_json.exists():
        return
    print(
        "\nKaggle credentials not found.\n"
        "1. Go to https://www.kaggle.com/settings/account -> API -> 'Create New Token'\n"
        "   This downloads a file named kaggle.json.\n"
        "2. Upload it in Colab (Files pane, or run:\n"
        "       from google.colab import files; files.upload()\n"
        "   and select kaggle.json).\n"
        "3. Then run:\n"
        f"       mkdir -p {Path.home()}/.kaggle && "
        f"cp kaggle.json {Path.home()}/.kaggle/kaggle.json && "
        f"chmod 600 {Path.home()}/.kaggle/kaggle.json\n"
    )
    raise SystemExit(1)


def _already_extracted(dataset: str) -> bool:
    d = PATHS.raw_dataset(dataset)
    return d.exists() and any(d.iterdir())


def _download_kaggle(name: str, cfg: dict, force: bool) -> Path:
    archive_path = PATHS.archives / cfg["expected_archive"]
    if archive_path.exists() and not force:
        log.info("%s archive already in Drive, skipping download.", name)
        return archive_path

    _check_kaggle_credentials()
    log.info("Downloading %s from Kaggle (%s)...", name, cfg["slug"])
    tmp_dir = PATHS.local_root / "_dl_tmp" / name
    tmp_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["kaggle", "datasets", "download", "-d", cfg["slug"], "-p", str(tmp_dir)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("Kaggle download failed: %s", result.stderr)
        raise SystemExit(1)

    downloaded = list(tmp_dir.glob("*.zip"))
    if not downloaded:
        log.error("Kaggle download reported success but no .zip found in %s", tmp_dir)
        raise SystemExit(1)
    drive_io.push_archive(downloaded[0], name=cfg["expected_archive"])
    shutil.rmtree(tmp_dir, ignore_errors=True)
    return archive_path


def _manual_fallback(name: str, cfg: dict) -> None:
    archive_path = PATHS.archives / cfg["expected_archive"]
    print(
        f"\nAutomated download for '{name}' failed or is unsupported.\n"
        f"Please download it manually and place the file at exactly:\n"
        f"    {archive_path}\n"
        f"Notes: {cfg.get('notes', '').strip()}\n"
        "Then re-run this script — it will detect the file and skip re-downloading.\n"
    )


def _download_http(name: str, cfg: dict, force: bool) -> Path | None:
    archive_path = PATHS.archives / cfg["expected_archive"]
    if archive_path.exists() and not force:
        log.info("%s archive already in Drive, skipping download.", name)
        return archive_path

    import urllib.request
    import urllib.error

    log.info("Attempting HTTP download of %s from %s ...", name, cfg["url"])
    tmp_path = PATHS.local_root / "_dl_tmp" / cfg["expected_archive"]
    tmp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        urllib.request.urlretrieve(cfg["url"], tmp_path)
        if tmp_path.stat().st_size < 1024:  # landing pages return tiny HTML, not the archive
            raise ValueError("Downloaded file is suspiciously small; likely not the real archive")
        drive_io.push_archive(tmp_path, name=cfg["expected_archive"])
        tmp_path.unlink(missing_ok=True)
        return archive_path
    except (urllib.error.URLError, ValueError, TimeoutError, OSError) as e:
        log.warning("Automated download of %s failed: %s", name, e)
        _manual_fallback(name, cfg)
        return None


def _download_git(name: str, cfg: dict, force: bool) -> Path:
    dest = PATHS.raw_dataset(name)
    if _already_extracted(name) and not force:
        log.info("%s already cloned/extracted, skipping.", name)
        return dest
    if dest.exists() and force:
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    log.info("Cloning %s from %s ...", name, cfg["repo_url"])
    result = subprocess.run(
        ["git", "clone", "--depth", "1", cfg["repo_url"], str(dest)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        log.error("git clone failed: %s", result.stderr)
        raise SystemExit(1)
    return dest


def _extract_zip(archive_path: Path, dataset: str) -> None:
    dest = PATHS.raw_dataset(dataset)
    dest.mkdir(parents=True, exist_ok=True)
    log.info("Extracting %s -> %s", archive_path, dest)
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(dest)
    log.info("Extraction complete for %s", dataset)


def process_dataset(name: str, cfg: dict, force: bool) -> None:
    if _already_extracted(name) and not force:
        log.info("%s already extracted at %s, nothing to do.", name, PATHS.raw_dataset(name))
        return

    kind = cfg["kind"]
    if kind == "kaggle":
        archive = _download_kaggle(name, cfg, force)
        local_archive = drive_io.pull_archive(archive.name)
        _extract_zip(local_archive, name)
        local_archive.unlink(missing_ok=True)
    elif kind == "http":
        archive = _download_http(name, cfg, force)
        if archive is None:
            return  # manual fallback message already printed
        local_archive = drive_io.pull_archive(archive.name)
        _extract_zip(local_archive, name)
        local_archive.unlink(missing_ok=True)
    elif kind == "git":
        _download_git(name, cfg, force)
    elif kind == "manual":
        _manual_fallback(name, cfg)
    else:
        raise ValueError(f"Unknown source kind '{kind}' for dataset '{name}'")

    tmp_dl = PATHS.local_root / "_dl_tmp"
    if tmp_dl.exists():
        shutil.rmtree(tmp_dl, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase A2: download raw datasets.")
    parser.add_argument("--only", choices=["plantvillage", "digipathos", "plantdoc"], default=None)
    parser.add_argument("--force", action="store_true", help="Re-download even if already present.")
    args = parser.parse_args()

    sources = _load_sources()
    names = [args.only] if args.only else list(sources.keys())

    for name in names:
        cfg = sources[name]
        log.info("=== Processing dataset: %s ===", name)
        process_dataset(name, cfg, args.force)

    print("\nSummary:")
    for name in names:
        d = PATHS.raw_dataset(name)
        n = sum(1 for _ in d.rglob("*")) if d.exists() else 0
        print(f"  {name}: {'OK' if _already_extracted(name) else 'MISSING'} ({n} files under {d})")


if __name__ == "__main__":
    main()
