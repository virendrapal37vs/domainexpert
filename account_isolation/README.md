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

### Per-account mode storage foundation (inactive)

`database/account_mode_db.py` stores mode under an exact existing username.
Unconfigured accounts default to Analyze. Reads avoid a process-wide cache;
writes accept only booleans and never modify another account's row. The table
is created only by explicitly calling init_account_mode_db. No application boot,
mode UI, order dispatch or sandbox lifecycle is wired to this module yet.
These storage tests do not establish that live orders honor per-account mode.
Next migration must cover service calls, API/session owner resolution, explicit
strategy-run mode and shared sandbox engine lifecycle before enabling trading.

### Mode owner resolution (disabled migration flag)

`DOMAINXPERT_ACCOUNT_MODES` defaults to false. Do not enable yet. When enabled,
settings_db.get_analyze_mode resolves an explicit owner/API key, otherwise a
request JSON apikey or browser session. API routes cannot borrow browser identity;
unknown owners and ownerless background calls raise instead of using global Live.
The per-account table is now created alongside per-user Groww credentials at boot.
Shared set_analyze_mode and apply_analyze_mode reject this migration mode before
writing settings or starting/stopping shared sandbox machinery. Lifecycle and
explicit owner propagation across background services remain incomplete. Current
staging behavior is unchanged while this flag remains false. Six resolver tests
cover session/API precedence, rejected fallback and explicit background identity.

### Account mode sandbox lifecycle (still disabled)

Account-mode transitions now use explicit owner resolution and the existing
bounded transition lock. Worker startup precedes mode persistence; startup failure
leaves the account's mode unchanged. Shared workers are never stopped by one
account switching Live, because other accounts and pre-existing sandbox orders
still need processing. Account-mode boot ensures workers without reading an
ownerless global mode. Restricted staging blocks transitions/worker startup.
Five tests use mocked workers; they are not broker execution tests.
Keep DOMAINXPERT_ACCOUNT_MODES=false: polling execution_engine quote helpers
still use ApiKeys.query.first(), and background owner propagation is unfinished.
This patch does not establish multi-user sandbox/trading readiness.

### Polling quote ownership

In per-user Groww mode the execution engine resolves API keys by the order/GTT
owner instead of the first ApiKeys row. Polling quote batches and caches use
(owner, symbol, exchange); missing keys/quotes never borrow another owner's data.
Order-manager immediate checks pass their owner, and GTT catch-up batches per
owner. Legacy mode retains its existing shared quote behavior. Nine synthetic
tests include the real extracted polling-cycle and quote-fetch method bodies;
no live broker request is made. Engine/manager modules also pass Python compile.
Keep account mode flag off: this does not finish WebSocket price-cache isolation,
all background mode call sites, or full live order dispatch validation.

### Shared sandbox WebSocket cache guard

Per-user Groww mode now forces polling sandbox execution, disables automatic
WebSocket upgrade, rejects direct WebSocket-engine startup, and ignores its
ownerless tick callback. Position MTM bypasses shared MarketDataService cache.
Position and holdings single/batch REST quotes resolve only self.user_id's API
key. Six mocked/source-method tests cover tick rejection, polling selection,
cache bypass and own-key REST access. Modules pass compile checks. This trades
sandbox tick latency for polling latency until owner-aware tick dispatch exists;
it is not a completed per-user WebSocket engine. Keep account mode flag off:
background mode callers, live order paths and account-wide isolation still need
integration verification. Existing processes must restart to load these changes;
do not toggle environment flags in a running process.

### Core service mode propagation (flag remains off)

Place-order mode decisions now pass their API key explicitly; an internal
force_live run bypasses the account-mode read as intended. API orderbook and
positions requests also pass their key, while existing explicit internal live
reads remain direct broker reads. API analyzer mode transitions propagate their
key into account lifecycle handling. Four tests execute real extracted service
function bodies with synthetic owner modes and mocked sandbox/broker boundaries:
Alice Analyze vs Bob Live, ownerless invalid-key rejection, and both read books.
No live order is submitted. These tests do not cover the remaining order types,
all lifecycle entry points, global analyzer log/statistics access or background
strategy/Flow/bot ownership. Keep DOMAINXPERT_ACCOUNT_MODES=false and staging
trading blocked until those paths and full-app two-account flows are verified.

### Remaining keyed order/read service checks

Thirty-three mode reads across 18 service files now propagate the available API
key: smart/options/multiorder/basket/split orders, modify/cancel/close operations,
GTT operations, funds/holdings/trades/order-status/open-position reads. Explicit
internal live read bypasses retain their original intent. Eight synthetic tests
execute real function bodies through their mode gate to verify key propagation;
these are not complete execution/fill tests. All 18 modified modules compile.
Keep account-mode flag off: runner/bot ownership, analyzer log access, remaining
lifecycle paths and full-app integration are not complete. A passing synthetic
suite is not authorization to enable public trading.

### Analyzer log ownership

Analyzer logs now have a nullable username column with an additive migration on
init_db. Existing rows remain unowned. Order-event log subscribers supply the
API key so the writer verifies and stores the owner. Per-user list/filter/export,
stats and clear queries are scoped through account_analyzer_query; API status
counts use the API key owner. Unknown identities reject access and ownerless
legacy logs are hidden in per-user mode. Legacy mode keeps existing visibility.
Five SQLite tests cover own query/count, isolated deletion, invalid key, legacy
visibility and idempotent additive migration. Non-event direct logging call sites
without an API key still write unowned rows, hidden from per-user views; their
owner propagation remains unfinished. This does not migrate general API logs or
complete full-app browser/export tests. Existing DB files should be backed up
before loading this schema migration on server. No production restart is needed.
Background audit: ScalpingRiskMonitor still resolves find_user_by_username()
without an owner (first user); do not enable multi-user trading yet.

### Shared scalping monitor guard (feature unavailable in multi-user mode)

Scalping's singleton resolves the first user and its persisted SL/tracked state
is not account-scoped. Until that storage/worker migration is complete, either
per-user Groww or account-mode flag disables the scalping blueprint (503 with
SCALPING_ACCOUNT_ISOLATION_PENDING) and prevents monitor startup, resync, ticks,
exits and first-user auth/mode resolution. Single-user legacy behavior is retained.
Nine tests execute the real monitor guard methods and Flask route gate, including
legacy route availability. This is an explicit feature block, not a multi-user
scalping implementation. Restart staging to load it; do not alter running flags.
Other background runners and general API logs remain under audit.

### General API log ownership

OrderLog has a nullable username column with an additive initialization migration.
Event subscribers pass their API key; direct writers may also supply an explicit
key or request payload apikey. Ownership is verified, never taken from payload
username. New top-level request apikey fields are removed before persistence.
Log list/search/pagination/export share the owner-filtered query; unowned rows
remain hidden in per-user mode. Existing logs are not re-attributed or redacted.
Four SQLite tests cover event/direct ownership, missing/invalid owner rejection,
nonmutation/redaction, legacy visibility and migration preservation. This does
not claim all direct writer call sites now propagate identity; logs whose callers
omit the key remain unowned. Backup staging DB before restart to apply migration.
Full HTTP export and background strategy execution are still pending verification.

### OpenScript run-start owner snapshot

Per-user OpenScript starts now resolve mode from the explicit run user and a
matching verified API key. Missing/mismatched identity or disabled account-mode
migration rejects the start before log creation/child spawning. Legacy mode
keeps its previous global reader and failure behavior. Five tests execute real
mode/read and early spawn function bodies with synthetic accounts, never spawning
a child. This does not certify script record ownership, stop/status permissions,
child execution isolation or run restoration. Shared strategy RiskTickFeed still
has a first-user API-key fallback and remains a blocker for public strategy use.
Keep account modes disabled and restricted staging active.

### Shared strategy risk-feed guard

Reviewed strategy HTTP routes already resolve stored strategies by username, but
RiskTickFeed uses a first-user key and ownerless symbol callbacks. Per-user flags
therefore make the strategy blueprint return explicit 503, skip module runtime
jobs/recovery, refuse direct engine.start_run and block shared feed key/WS/tick/
price-callback paths. Legacy single-user behavior remains enabled. Seven tests
exercise real method bodies and Flask gate with mocks; no strategy runs/orders
are created. This is a temporary feature block, not account-aware strategy risk
monitoring. Stop/status permissions of other runners, Python process isolation,
Flow/bot lifecycle and full two-account HTTP behavior remain unfinished.
Do not enable account modes or public trading. Restart staging to load guards.

### Running-app onboarding smoke check

With restricted staging already running on loopback 5001, run:

    ~/domainxpert-staging-venv/bin/python account_isolation/smoke_staging.py

The script validates this checkout's staging env, disables environment proxy
inheritance and redirects, checks blocked HTTP/socket paths, then creates two
random non-admin accounts via HTTP. It signs them in, saves dummy credentials,
tries an owner-field override, and verifies both exact DB records plus CSRF
rejection. Passwords/keys/responses are not printed. Two test users remain in the
staging DB and signup/login limits apply; do not repeatedly rerun after 429.
This script has been syntax-checked locally but must be run against the actual
staging process to establish an HTTP result. It does not establish trading,
WebSocket tenant delivery, email ownership, log export, or background isolation.

### Real-blueprint HTTP isolation tests (synthetic boundaries)

Ten additional tests register the real order/log/analyzer Flask blueprints.
Broker-session checks are replaced with the existing require_account decorator;
book-service responses and book template rendering are stubbed. The tests verify
session-owner token/API-key arguments and HTTP output for orderbook/positions,
real SQLite log list/stats/search/export ownership despite query-string owner
spoofing, anonymous rejection and own-only log clearing. Shared symbol/socket
providers are stubbed only to import the analyzer statistics module; its actual
statistics/query/CSV code executes. This is stronger than extracted function
checks but is not a full running-app broker integration test.

In per-user mode /analyzer/clear now requires POST (GET returns 405), with global
CSRF protection. Legacy mode still accepts the old GET. POST deletes only the
owner's rows older than 24 hours. No schema migration is added by this patch.

### Actual Socket.IO test-client delivery

Five transport tests run Flask-SocketIO test clients with the real account room
connect handler, emit helpers and order subscriber module. They verify own-only
order and Action Center delivery, ignored auth-payload usernames, anonymous/
unknown/non-broker-session connection rejection and dropped invalid-key events.
Synthetic API keys and Flask test sessions are used; this is not a Groww stream
or full app socket middleware test. The subscriber source module is loaded
without the package initializer to avoid starting unrelated messaging adapters.
Logout/revocation, session expiry and market-data proxy ownership remain pending.
The test environment now requires Flask-SocketIO; production deps are unchanged.
