#!/usr/bin/env python3
"""Rebuild the local jobs dashboard from data/seen_jobs.db.

Usage:  python scripts/build_dashboard.py
Opens:  data/dashboard.html  (open it in your browser)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.dashboard import build_dashboard

if __name__ == "__main__":
    out = build_dashboard()
    print(f"wrote {out}")
