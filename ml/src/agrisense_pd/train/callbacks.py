"""Ultralytics training callback that periodically syncs checkpoints to
Drive. This is what makes a Colab disconnect survivable: without it, a
9-hour training run that dies at hour 8 loses everything, since /content
is wiped on reconnect (see plant-disease-implementation-plan.md
section 1.1 and 1.6).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import drive_io
from ..logging_utils import get_logger

log = get_logger("train.callbacks")


def attach_checkpoint_sync(model: Any, drive_dest_dir: Path, every_n_epochs: int = 2) -> None:
    """Registers an on_fit_epoch_end callback on an ultralytics model that
    copies last.pt (every `every_n_epochs` epochs) and best.pt (whenever
    it changes) to `drive_dest_dir`, atomically.
    """
    state = {"last_synced_epoch": -1}

    def _on_fit_epoch_end(trainer) -> None:
        epoch = getattr(trainer, "epoch", None)
        if epoch is None:
            return
        due = (epoch - state["last_synced_epoch"]) >= every_n_epochs
        is_final = epoch + 1 >= getattr(trainer, "epochs", epoch + 1)
        if not (due or is_final):
            return

        wdir = getattr(trainer, "wdir", None) or (Path(trainer.save_dir) / "weights")
        last_pt = Path(wdir) / "last.pt"
        best_pt = Path(wdir) / "best.pt"

        try:
            if last_pt.exists():
                drive_io.sync_checkpoint(last_pt, drive_dest_dir)
            if best_pt.exists():
                drive_io.sync_checkpoint(best_pt, drive_dest_dir)
            state["last_synced_epoch"] = epoch
            log.info("Synced checkpoints to Drive at epoch %d", epoch)
        except Exception as e:  # noqa: BLE001 - never let a Drive hiccup kill training
            log.warning("Checkpoint sync failed at epoch %d: %s", epoch, e)

    model.add_callback("on_fit_epoch_end", _on_fit_epoch_end)


def sync_final(run_dir: Path, drive_dest_dir: Path) -> None:
    """Called once after model.train() returns, to make sure the final
    best.pt/last.pt are on Drive even if the last periodic sync missed them.
    """
    wdir = Path(run_dir) / "weights"
    for name in ("best.pt", "last.pt"):
        p = wdir / name
        if p.exists():
            drive_io.sync_checkpoint(p, drive_dest_dir)
