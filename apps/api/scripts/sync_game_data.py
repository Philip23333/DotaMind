"""Compatibility entry point for the Valve data sync command."""

from __future__ import annotations

import sys
from pathlib import Path

API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.integrations.valve.game_data_sync import main  # noqa: E402, I001


if __name__ == "__main__":
    main()
