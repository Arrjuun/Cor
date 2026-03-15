"""Session serialization / deserialization."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

SESSION_VERSION = "1.0"


class SessionModel:
    """Serializes and deserializes full application state to/from JSON."""

    # ------------------------------------------------------------------ #
    # Save                                                                 #
    # ------------------------------------------------------------------ #

    def save(self, filepath: str, state: dict[str, Any]) -> None:
        """
        Save application state to a JSON file.

        Args:
            filepath: Path to write (extension .csa or .json).
            state: Dict produced by collecting state from all presenters.
        """
        payload = {
            "version": SESSION_VERSION,
            "created": datetime.now().isoformat(),
            **state,
        }
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, default=str)

    # ------------------------------------------------------------------ #
    # Load                                                                 #
    # ------------------------------------------------------------------ #

    def load(self, filepath: str) -> dict[str, Any]:
        """
        Load and return application state from a JSON file.

        Raises:
            FileNotFoundError, json.JSONDecodeError, ValueError on bad data.
        """
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)

        self._validate(data)
        return data

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _validate(data: dict) -> None:
        if "version" not in data:
            raise ValueError("Session file is missing 'version' field.")
        if data["version"] != SESSION_VERSION:
            raise ValueError(
                f"Session version mismatch: expected {SESSION_VERSION}, "
                f"got {data['version']}"
            )
