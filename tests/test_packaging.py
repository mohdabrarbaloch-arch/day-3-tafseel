"""Serverless packaging guarantees.

These three tests exist because Day 1 shipped with a broken bundle: `builds` compiled
only api/index.py, so `from app.main import app` failed at import and every /api/* route
returned 500 while `/` still served a friendly HTML shell.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_vercel_config_uses_modern_functions_key():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert "functions" in config
    assert "app/**" in config["functions"]["api/index.py"]["includeFiles"]


def test_vercel_config_has_no_legacy_builds_key():
    config = json.loads((ROOT / "vercel.json").read_text())
    assert "builds" not in config, "legacy builds block bundles only the entrypoint"
    assert "routes" not in config, "legacy routes catch-all hides a crashing backend"


def test_entrypoint_imports_the_app_package():
    source = (ROOT / "api" / "index.py").read_text()
    assert "from app.main import app" in source


def test_static_mount_is_guarded_by_directory_check():
    """StaticFiles raises at import time when the directory is missing."""
    source = (ROOT / "app" / "main.py").read_text()
    assert "STATIC_DIR.is_dir()" in source


def test_init_db_runs_at_import_time():
    """Vercel never fires lifespan events, so a lifespan-only init leaves no tables."""
    source = (ROOT / "app" / "main.py").read_text()
    assert "\ninit_db()" in source


def test_database_url_falls_back_to_tmp_on_vercel():
    source = (ROOT / "app" / "config.py").read_text()
    assert "/tmp/tafseel.db" in source
