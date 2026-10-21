"""Shared test configuration."""

from __future__ import annotations

import os

# Qt GUI tests run without a visible desktop.  Set this before any test module
# imports PySide6.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
