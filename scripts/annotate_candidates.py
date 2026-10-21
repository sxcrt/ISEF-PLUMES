#!/usr/bin/env python
"""Launch the independent plume-candidate annotation GUI."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from planetary_plume.review_app import main
except ModuleNotFoundError as exc:
    if exc.name and (exc.name == "PySide6" or exc.name.startswith("PySide6.") or exc.name == "shiboken6"):
        print(
            "PySide6 is required for the annotation GUI.\n"
            "Install it with:\n"
            "  python -m pip install -r requirements-gui.txt\n"
            "or:\n"
            "  python -m pip install 'PySide6>=6.8,<7'",
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    raise


if __name__ == "__main__":
    raise SystemExit(main())
