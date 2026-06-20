"""Shim: resolve the real app module from backend/ for Render's buildpack.
Render runs `uvicorn app:app` from the repo root; this file redirects to
backend/app/main.py so imports work without changing the dashboard config.
"""
import os
import sys

# Add backend/ to Python path so `from app.main import app` resolves
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.main import app
