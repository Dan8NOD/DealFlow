#!/usr/bin/env python3
"""
run_sync.py — Run all enrichment sync scripts in sequence.

Usage:  python3 scripts/run_sync.py

Runs:
  1. sync_obsidian.py — Parse Obsidian LEASING notes → properties
  2. sync_spreadsheet.py — Import xlsx data → leads, properties, applications
"""

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent


def run(script_name):
    """Run a sync script and print its output."""
    print(f"\n{'='*60}")
    print(f"  Running: {script_name}")
    print(f"{'='*60}")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / script_name)],
        capture_output=False,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: {script_name} failed (exit code {result.returncode})")
        if result.stderr:
            print(result.stderr)
        sys.exit(result.returncode)
    return result


if __name__ == "__main__":
    print("Renter Portal Data Sync")
    print("=======================")

    run("sync_obsidian.py")
    run("sync_spreadsheet.py")

    print(f"\n{'='*60}")
    print("  ALL SYNC COMPLETE")
    print(f"{'='*60}")
