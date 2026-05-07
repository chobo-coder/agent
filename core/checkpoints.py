"""Checkpoint management for intermediate DataFrames."""

import os
from pathlib import Path

import pandas as pd

import config
from core.state_machine import WorkflowState


class CheckpointManager:
    """Saves and loads intermediate DataFrames to disk."""

    def __init__(self, checkpoint_dir: str | None = None):
        self._dir = Path(checkpoint_dir or config.CHECKPOINT_DIR)
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, state: WorkflowState, dataframes: dict[str, pd.DataFrame]) -> None:
        """Save DataFrames as parquet files for the given state."""
        state_dir = self._dir / state.name.lower()
        state_dir.mkdir(parents=True, exist_ok=True)

        for name, df in dataframes.items():
            path = state_dir / f"{name}.parquet"
            df.to_parquet(path, index=False)

    def load(self, state: WorkflowState, name: str) -> pd.DataFrame | None:
        """Load a checkpoint DataFrame."""
        path = self._dir / state.name.lower() / f"{name}.parquet"
        if path.exists():
            return pd.read_parquet(path)
        return None

    def exists(self, state: WorkflowState, name: str) -> bool:
        path = self._dir / state.name.lower() / f"{name}.parquet"
        return path.exists()

    def clear(self) -> None:
        """Remove all checkpoints."""
        import shutil

        if self._dir.exists():
            shutil.rmtree(self._dir)
            self._dir.mkdir(parents=True, exist_ok=True)
