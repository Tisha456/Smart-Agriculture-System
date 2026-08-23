"""State machine for the Stage 2 per-species training loop (Phase D2).

~20-30 separate trainings cannot fit in one free-tier Colab session, so
the loop must be resumable: re-running the same cell after a disconnect
continues rather than restarting (see
plant-disease-implementation-plan.md section 1.6).

state/stage2_progress.json:
{
  "tomato": {"status": "done", "classes": 10, "val_top1": 0.981,
             "test_top1": 0.974, "run_dir": "...", "finished_at": "..."},
  "corn":   {"status": "in_progress", "epochs_done": 12}
}
Statuses: pending | in_progress | done | failed
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ..config import PATHS
from ..logging_utils import get_logger

log = get_logger("resume_state")


def load() -> dict:
    path = PATHS.stage2_progress_json()
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save(state: dict) -> None:
    path = PATHS.stage2_progress_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    tmp.replace(path)


def get_status(state: dict, species: str) -> Optional[str]:
    return state.get(species, {}).get("status")


def mark_pending(state: dict, species: str) -> None:
    state.setdefault(species, {})["status"] = "pending"


def mark_in_progress(state: dict, species: str, epochs_done: int = 0) -> None:
    state.setdefault(species, {})
    state[species]["status"] = "in_progress"
    state[species]["epochs_done"] = epochs_done


def mark_done(state: dict, species: str, classes: int, val_top1: float,
              test_top1: float, run_dir: str) -> None:
    import datetime

    state[species] = {
        "status": "done",
        "classes": classes,
        "val_top1": val_top1,
        "test_top1": test_top1,
        "run_dir": run_dir,
        "finished_at": datetime.datetime.utcnow().isoformat() + "Z",
    }


def mark_failed(state: dict, species: str, error: str) -> None:
    state.setdefault(species, {})
    state[species]["status"] = "failed"
    state[species]["error"] = error
