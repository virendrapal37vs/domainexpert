"""Commands use their own config/database, never the OpenAlgo .env."""
import argparse
import json
import os
import re
import secrets
from pathlib import Path

from cryptography.fernet import Fernet

CONFIG = Path.home() / ".config" / "domainxpert-preview" / "config.json"
parser = argparse.ArgumentParser(description="Local-only DomainXpert onboarding prototype")
parser.add_argument("command", choices=["init", "serve", "invite"])
parser.add_argument("--allow-groww-check", action="store_true", help="Enable read-only Groww token and quote requests (serve only)")
args = parser.parse_args()
if args.allow_groww_check and args.command != "serve":
    parser.error("--allow-groww-check can only be used with serve")

if args.command == "init":
    CONFIG.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    data = Path.home() / ".local" / "share" / "domainxpert-preview"
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    settings = {"SECRET_KEY": secrets.token_urlsafe(48),
                "PREVIEW_ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "PREVIEW_DATABASE": str(data / "onboarding.db")}
    try:
        fd = os.open(CONFIG, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit("Preview config already exists; kept existing encryption keys.")
    with os.fdopen(fd, "w") as stream:
        json.dump(settings, stream)
    print("Separate preview config created. No production files changed.")
    raise SystemExit(0)

if not CONFIG.exists():
    raise SystemExit("First run: python -m tenant_preview init")
from tenant_preview.app import create_app
settings = json.loads(CONFIG.read_text())
settings["ALLOW_GROWW_CHECK"] = args.allow_groww_check
app = create_app(settings)
if args.command == "invite":
    address = input("Invite email: ").strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", address) or len(address) > 120:
        raise SystemExit("Invalid email")
    token = app.extensions["preview_store"].invite(address)
    print("One-time invitation (valid 24 hours):", token)
else:
    app.run(host="127.0.0.1", port=5051, debug=False)
