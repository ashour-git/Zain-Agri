"""Deployment settings that are easy to lose and expensive when lost."""

import json
from pathlib import Path

VERCEL_JSON = Path(__file__).resolve().parents[3] / "vercel.json"


def test_functions_run_next_to_the_database() -> None:
    """Neon is in aws-eu-central-1 (Frankfurt). Vercel's default region is
    iad1 (Washington): every query then crosses the Atlantic, about 100 ms
    each, and a 6-query request took 750 ms. fra1 is Frankfurt.
    """
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

    assert config.get("regions") == ["fra1"]


def test_nightly_backup_cron_is_scheduled() -> None:
    """01:00 UTC is 03:00 Cairo, after closing time (spec 2026-11-12 §4)."""
    config = json.loads(VERCEL_JSON.read_text(encoding="utf-8"))

    assert config.get("crons") == [
        {"path": "/api/v1/internal/backups/run", "schedule": "0 1 * * *"}
    ]
