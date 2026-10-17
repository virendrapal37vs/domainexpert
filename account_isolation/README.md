# Main-app account credentials — development integration

This is an incremental integration patch, **not a production multi-user launch**.
It does not enable signup, create main-app accounts, import preview accounts,
change production settings, or deploy the frontend build.

## Implemented

- Three shared settings blueprints (`admin`, `broker_credentials`,
  `system_permissions`) now require an existing database user with `is_admin=True`.
  This role check applies regardless of the per-user feature flag. Existing route
  session checks and global CSRF protection are retained. A client role field is
  never accepted as authority.
- New `account_broker_credentials` table uses username + broker as its key.
  Groww API keys/secrets use the application's existing encryption helper and keys.
- GET/PUT `/api/account/brokers/groww` operates only on `session['user']` after
  looking up the actual account. It ignores supplied owner IDs, returns no secret,
  and requires the existing global CSRF token for PUT. The feature is off by default.
- Credential replacement is refused during a fully logged-in broker session. A
  user must sign out/sign in to change credentials. In scoped mode automatic
  broker-session resume is disabled to avoid reusing tokens minted from global keys.
- In scoped mode the broker page has an own-credentials form; Connect remains
  disabled until credentials are saved. The Groww callback passes that user's
  credentials explicitly. The Groww adapter never falls back to global credentials
  in this mode. Other broker callbacks are refused in this experimental mode.
- Scoped broker config returns no global API key and verifies the session account.
- No raw Groww login failure body is logged by the checksum request handler.

## Test on the development worktree

Do not apply this patch in `/home/ubuntu/openalgo` or restart `openalgo.service`.
From `/home/ubuntu/domainxpert-multiuser`:

```bash
~/.local/bin/uv pip install --python ~/domainxpert-preview-venv/bin/python \
  -r account_isolation/requirements-test.txt
~/domainxpert-preview-venv/bin/python -m pytest -q -o addopts='' \
  account_isolation/tests --confcutdir=account_isolation/tests
~/domainxpert-preview-venv/bin/python -m pytest -q -o addopts='' \
  tenant_preview/tests --confcutdir=tenant_preview/tests
cd frontend
npm ci
npm run test:run -- src/components/auth/OwnGrowwCredentials.test.tsx
npm run build -- --outDir dist-account-staging
```

Expected backend results: 8 account tests and 27 preview tests. UI: 2 tests.
The account tests use synthetic users, temporary SQLite DBs and test encryption
keys. They exercise the real credential API/store, CSRF, database-backed role
checks, plus extracted real Groww/auth callback function bodies to avoid booting
unrelated services. This is **not** an end-to-end full-app startup test. Tests make
no live broker requests and do not use production keys or databases.

Local validation used Python 3.12, Node 24 and the existing npm lockfile. Build
succeeded with the project's existing large-chunk warning. The built distribution
is not included in the patch; source/build output must be deployed together later.

## Feature activation — dedicated staging only, not now

`DOMAINXPERT_PER_USER_GROWW=true` selects the new credential path. Without it,
the legacy single-user Groww credential path is retained; new credential APIs
return 404. Never turn this flag on against the current production database as
an attempted multi-user rollout. Existing live cookies/tokens/background jobs
have not been migrated by this patch.

A staging process needs its own .env, databases, encryption keys, ports, service,
broker credentials, and disabled strategy/background execution. Copying the
production .env or database is not an acceptable staging setup. The separate
onboarding preview configuration cannot be used as the full app configuration.
Do not run the full app on this development worktree until that setup is prepared.

## Remaining blockers

- Preview identities are not main-app identities. A reviewed account provisioning
  and recovery/verification flow is still needed; do not reopen `/setup`.
- First-admin/last-auth assumptions in background services remain to be replaced.
- Audit all orders, API keys, WebSocket subscriptions, file paths, sandbox state,
  strategies and logs for cross-account access. Existing user-scoped records alone
  are not proof of tenant isolation.
- Untrusted Python strategy execution requires isolated execution environments,
  not subprocesses running as the application OS user.
- Test full staging startup, session reuse/revocation, two-account broker flow,
  UI authorization and permission changes before deployment.
- Groww access still needs a live check after the outstanding 403 is resolved.

Do not merge this feature branch into the production deployment yet.

## Restricted main-app staging guard

`DOMAINXPERT_STAGING_SAFE=true` is an onboarding-only staging mode. It validates
loopback ports, dedicated database file paths, distinct cookies, empty global
broker keys, and disabled ngrok/debug/MCP/order updates. It selects the already
built `frontend/dist-account-staging` directory.

Only reviewed setup/login/session/static/own-credential endpoints are admitted.
Broker callbacks, trading APIs, strategies and admin APIs return 403. Socket.IO
and `/ws` are also blocked at the WSGI middleware layer. Boot skips broker
keepalive, order adapters, health-monitor startup, cache restoration, websocket
proxy startup and scheduler/bot/strategy initialization after database creation.
Normal production startup is unchanged when the flag is absent.

Use `account_isolation/start_staging.py` with a **separate full-app venv**. The
preview/test venv does not contain the full app dependencies. The launcher refuses
to start without the staging flag and a valid config, uses one gthread worker,
binds to 127.0.0.1:5001, and does not use the websocket proxy launcher.

Guard tests validate bad configs, endpoint denial, the outer websocket gate, and
startup call guards. Full-app staging startup is still to be verified on the server.
This does not make shared trading or arbitrary Python execution tenant-safe.
Do not enable broker connections or invite outside users from this staging mode.

### Direct signup

Set `DOMAINXPERT_PUBLIC_SIGNUP=true` in the separate staging `.env` to enable
`/signup` and POST `/auth/signup`. Complete initial administrator setup first.
New accounts always have `is_admin=False`, use the existing password hashing
and encrypted TOTP storage, and then sign in through the existing login flow.
The endpoint uses global CSRF protection and a five-per-hour IP limit. Current
limiter storage must be shared before scaling to multiple workers/instances.
Email syntax is validated; email ownership verification is not implemented.
Restricted staging continues to block broker connections and trading.

### Order notification isolation (partial audit)

With per-user Groww enabled, the order-event Socket.IO subscriber resolves the
owner from the event API key and emits only to that account's hashed room.
Missing/invalid ownership drops the event. Root connections require an existing
broker-authenticated session and join only the session owner's room; auth payload
usernames are ignored. Legacy mode is unchanged. Restricted staging still blocks
all Socket.IO transport. Tests use synthetic events and mocked transport, not live
broker connections. Other direct emit sites, order-feed adapters, position requests,
logout/session revocation and background jobs still require isolation review.

Action Center follow-up: its five pending-order notification sites now send to
the validated session owner's room in per-account mode. Tests cover scoped
helper delivery and all five source call sites. The reviewed HTML positions route
looks up the broker token by session username; this is code review evidence,
not live two-account brokerage validation. Remaining websocket adapters, session
revocation and background job ownership are not certified by these checks.

WebSocket config follow-up: in per-user mode the proxy config loader requires
an active matching Groww auth row, Groww enabled in VALID_BROKERS and saved
credentials for that username. Missing/revoked/mismatched records fail closed;
no global environment credentials are returned. Seven helper tests use fake
users and credentials. Actual broker WebSocket handshakes remain untested.
Audit blocker: settings_db.get_analyze_mode/set_analyze_mode still use one
instance-wide row/cache. Do not enable multi-user trading before changing mode
resolution across session, API and background execution paths.
