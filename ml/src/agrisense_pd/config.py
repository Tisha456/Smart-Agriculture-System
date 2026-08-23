"""Central configuration: loads configs/paths.yaml, exposes every path used
anywhere in the pipeline, and owns seeding. No module outside this file
should hardcode a path — see plant-disease-implementation-plan.md section 2.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

_THIS_FILE = Path(__file__).resolve()
# ml/src/agrisense_pd/config.py -> ml/
ML_ROOT = _THIS_FILE.parents[2]
CONFIGS_DIR = ML_ROOT / "configs"


def _load_yaml(name: str) -> dict:
    path = CONFIGS_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file {path}. Run from a checkout that includes ml/configs/."
        )
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@dataclass
class Paths:
    drive_root: Path
    local_root: Path

    # drive/
    archives: Path = field(init=False)
    manifests: Path = field(init=False)
    drive_models: Path = field(init=False)
    exported: Path = field(init=False)
    artifacts: Path = field(init=False)
    state: Path = field(init=False)

    # local/
    raw: Path = field(init=False)
    clean: Path = field(init=False)
    stage1: Path = field(init=False)
    stage2: Path = field(init=False)
    runs: Path = field(init=False)

    def __post_init__(self) -> None:
        self.archives = self.drive_root / "archives"
        self.manifests = self.drive_root / "manifests"
        self.drive_models = self.drive_root / "models"
        self.exported = self.drive_root / "exported"
        self.artifacts = self.drive_root / "artifacts"
        self.state = self.drive_root / "state"

        self.raw = self.local_root / "data" / "raw"
        self.clean = self.local_root / "data" / "clean"
        self.stage1 = self.local_root / "data" / "stage1_species"
        self.stage2 = self.local_root / "data" / "stage2_disease"
        self.runs = self.local_root / "runs"

    # --- convenience accessors -------------------------------------------------
    def raw_dataset(self, name: str) -> Path:
        return self.raw / name

    def master_csv(self) -> Path:
        return self.manifests / "master.csv"

    def taxonomy_map_csv(self) -> Path:
        return self.manifests / "taxonomy_map.csv"

    def fingerprints_csv(self) -> Path:
        return self.manifests / "fingerprints.csv"

    def fingerprints_partial_csv(self) -> Path:
        return self.manifests / "fingerprints.partial.csv"

    def rejected_csv(self) -> Path:
        return self.manifests / "rejected.csv"

    def species_index_json(self) -> Path:
        return self.manifests / "species_index.json"

    def condition_index_json(self) -> Path:
        return self.manifests / "condition_index.json"

    def stage1_models(self) -> Path:
        return self.drive_models / "stage1"

    def stage2_models(self, species: Optional[str] = None) -> Path:
        base = self.drive_models / "stage2"
        return base / species if species else base

    def stage2_progress_json(self) -> Path:
        return self.state / "stage2_progress.json"

    def log_file(self, script_name: str) -> Path:
        d = self.artifacts / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d / f"{script_name}.log"


def _detect_on_colab() -> bool:
    return "COLAB_GPU" in os.environ or Path("/content").exists()


def load_raw() -> dict:
    return _load_yaml("paths.yaml")


def get_paths() -> Paths:
    """Build the Paths object from paths.yaml, honoring env var overrides
    (AGRISENSE_PD_DRIVE_ROOT / AGRISENSE_PD_LOCAL_ROOT) for local/dev use
    off of Colab, e.g. running the test suite on a laptop.
    """
    raw = load_raw()
    drive_root = Path(os.environ.get("AGRISENSE_PD_DRIVE_ROOT", raw["drive_root"]))
    local_root = Path(os.environ.get("AGRISENSE_PD_LOCAL_ROOT", raw["local_root"]))
    return Paths(drive_root=drive_root, local_root=local_root)


PATHS = get_paths()
_RAW_CFG = load_raw()
SEED: int = _RAW_CFG.get("seed", 42)

# TRAINING_DATASETS feed the taxonomy/manifest/training pipeline.
# EVAL_DATASETS (PlantDoc) are real-world test-only and must never be
# merged into training — see plant-disease-implementation-plan.md
# section "E1". DATASETS is the union, used only for folder bookkeeping
# (ensure_dirs) and CLI --only choices; nothing merges across the two
# groups implicitly.
TRAINING_DATASETS: list[str] = _RAW_CFG.get("training_datasets", ["plantvillage"])
EVAL_DATASETS: list[str] = _RAW_CFG.get("eval_datasets", ["plantdoc"])
DATASETS: list[str] = sorted(set(TRAINING_DATASETS) | set(EVAL_DATASETS))


def set_seeds(seed: int = SEED) -> None:
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np

        np.random.seed(seed)
    except ImportError:
        pass
    try:
        import torch

        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
    except ImportError:
        pass


def ensure_dirs() -> None:
    """Create the full Drive + local folder skeleton (idempotent)."""
    p = PATHS
    for d in (p.archives, p.manifests, p.drive_models, p.exported, p.artifacts, p.state):
        d.mkdir(parents=True, exist_ok=True)
    for d in (p.raw, p.clean, p.stage1, p.stage2, p.runs):
        d.mkdir(parents=True, exist_ok=True)
    for name in DATASETS:
        (p.raw / name).mkdir(parents=True, exist_ok=True)
    (p.clean / "rejected").mkdir(parents=True, exist_ok=True)


def env_report() -> None:
    """Print GPU/torch/disk diagnostics. Hard-fails (raises) if no GPU is
    available, since silently training on CPU wastes hours on Colab.
    """
    import shutil

    print(f"On Colab: {_detect_on_colab()}")
    print(f"Drive root: {PATHS.drive_root}")
    print(f"Local root: {PATHS.local_root}")

    for label, path in (("Local disk", PATHS.local_root), ("Drive", PATHS.drive_root)):
        try:
            total, used, free = shutil.disk_usage(
                path if path.exists() else path.parent if path.parent.exists() else Path(".")
            )
            print(f"{label} free space: {free / 1e9:.1f} GB")
        except OSError:
            print(f"{label}: could not stat (path not mounted yet)")

    try:
        import torch
    except ImportError as e:
        raise RuntimeError("torch is not installed") from e

    print(f"torch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        raise RuntimeError(
            "No GPU detected. In Colab: Runtime -> Change runtime type -> "
            "Hardware accelerator -> GPU (T4). Training on CPU is not supported "
            "by this pipeline — it would take far too long."
        )
    print(f"GPU: {torch.cuda.get_device_name(0)}")
    vram_gb = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"VRAM: {vram_gb:.1f} GB")
    print(f"CUDA version (torch build): {torch.version.cuda}")

    try:
        import ultralytics

        print(f"ultralytics version: {ultralytics.__version__}")
    except ImportError:
        print("ultralytics: NOT INSTALLED")

    print("Environment check passed.")


if __name__ == "__main__":
    ensure_dirs()
    env_report()
