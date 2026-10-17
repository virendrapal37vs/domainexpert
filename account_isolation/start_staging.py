"""Validated staging launcher. Run with the separate full-app staging venv."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
os.chdir(root)
load_dotenv(root / ".env", override=True)
from utils.staging_mode import staging_safe, validate_staging_config
if not staging_safe():
    raise SystemExit("Refusing startup: DOMAINXPERT_STAGING_SAFE must be true in this checkout's .env")
validate_staging_config(root)
if not (root / "frontend" / "dist-account-staging" / "index.html").is_file():
    raise SystemExit("Build frontend/dist-account-staging before starting staging")
# Explicit bind, one process, no reload, no external websocket proxy launcher.
os.execv(sys.executable, [sys.executable, "-m", "gunicorn", "--worker-class", "gthread",
                         "--workers", "1", "--threads", "8", "--bind", "127.0.0.1:5001",
                         "--timeout", "180", "app:app"])
