# DomainXpert Trade — isolated onboarding prototype

Status: **development preview, not multi-user trading**. Additive code only;
no existing OpenAlgo routes, production config, databases or services are modified.

Implemented:
- Operator creates email-bound invitations through a local CLI; no public invite API.
- Invitation expires in 24 hours and is consumed atomically with account creation.
- Each user can register, log in/out, and save/check/delete their own Groww credentials.
- Argon2 password hashes, Fernet encrypted credentials, CSRF protection,
  30-minute sessions, rate limits and responses marked no-store.
- No broker requests or orders. No Python execution or WebSocket proxy.
- No owner ID from client input is used to select a credential record.

This does **not** add users to the live OpenAlgo database. A preview profile will
not log into the production dashboard. Use dummy broker credentials in this build.

## Install on the existing development worktree

Extract this package into `/home/ubuntu/domainxpert-multiuser`, not `~/openalgo`.

```bash
cd ~/domainxpert-multiuser
~/.local/bin/uv venv --python 3.12 ~/domainxpert-preview-venv
~/.local/bin/uv pip install --python ~/domainxpert-preview-venv/bin/python \
  -r tenant_preview/requirements.txt pytest
~/domainxpert-preview-venv/bin/python -m pytest -q -o addopts='' \
  tenant_preview/tests --confcutdir=tenant_preview/tests
~/domainxpert-preview-venv/bin/python -m tenant_preview init
~/domainxpert-preview-venv/bin/python -m tenant_preview invite
~/domainxpert-preview-venv/bin/python -m tenant_preview serve
```

The invitation command asks for a test user's email and prints a one-time code.
Keep the serve command running. In a **new Windows PowerShell** window:

```powershell
ssh -i "$env:USERPROFILE\Downloads\whatdesk-key.pem" -N -L 5051:127.0.0.1:5051 ubuntu@51.20.169.9
```

Open `http://127.0.0.1:5051` on Windows. Register with the invited email and code,
then sign in. A second invitation/account can be tested in an incognito window.

Do not open port 5051 in AWS, change Nginx, bind to 0.0.0.0, or run this preview
as the production service. Cookie Secure is false ONLY for the localhost SSH
forward. Flask's server and memory rate limiter are for a single-process preview.

Config: `~/.config/domainxpert-preview/config.json` (0600).
Data: `~/.local/share/domainxpert-preview/onboarding.db` (0600 in private directory).
Do not commit these paths, invitation codes, or encryption keys. `init` refuses
to overwrite existing keys. Stop with Ctrl+C. The production site is unaffected.

## Verification

Nine automated tests cover cross-account reads/writes/deletes, forged owner IDs,
password hashing and encrypted storage, unauthenticated access/logout, CSRF,
invitation binding/expiry/reuse/concurrent consumption, invalid input/login, and
absence of production/trading routes, and enforced login rate limits. No live broker calls are used.

## Findings in the original app

- `blueprints/core.py:setup` creates only an initial administrator.
- `blueprints/broker_credentials.py` reads/writes global .env settings.
- `broker/groww/api/auth_api.py:authenticate_broker` uses global broker key/secret.
- `blueprints/auth.py:get_broker_config` returns the global API key to a session user.
- `services/scalping_risk_monitor_service.py` and
  `services/strategy_module/tick_feed.py` select the first admin in some paths.
- `blueprints/python_strategy.py:get_active_broker` selects the most recent auth;
  strategy ownership allows legacy ownerless strategies; execution is a subprocess
  under the application OS identity. This is not untrusted tenant isolation.

## Required before shared trading

1. Choose deployment isolation. For untrusted users who can upload Python, prefer
   a separately isolated execution environment per user, without host mounts or
   production secrets, with resource/network limits; an OS subprocess is insufficient.
2. Move broker credentials to a reviewed per-user resolver without process-global
   env mutation or fallback to the administrator's credentials. Migrate the admin
   separately; verify account identity from broker responses.
3. Audit every REST, session, API-key, background job, sandbox, order mode, log,
   strategy, file path, and WebSocket route for ownership and authorization.
4. Enforce admin-only access to instance configuration and system-management APIs.
5. Connect the reviewed identity layer to the trading app, implement account
   suspension/revocation and credential rotation; provide email verification/reset
   and TOTP before public signup.
6. Run two-account integration tests across real dashboard flows and mocked broker
   requests, then sandbox verification. Groww's current 403 remains unresolved.
7. Deploy staging with separate keys/databases, TLS, persistent rate limiting,
   backups, and failure rollback before production.

This package is a first milestone, not proof of complete tenant isolation.
Keep original project licensing and notices with distributions.
