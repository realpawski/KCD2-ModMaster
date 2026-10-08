#!/usr/bin/env python3
"""Launcher for KCD2 ModMaster."""
import sys
from pathlib import Path

# Ensure src/ is in sys.path
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))

from app.main import run

if __name__ == "__main__":
    sys.exit(run())
