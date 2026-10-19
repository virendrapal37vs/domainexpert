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

### Account session notifications and socket reconnect validation

Logout, password reset/change, session-expiry and login session-count event sites
now use an account-scoped session event helper in per-user mode. force_logout
emits to that account and disconnects its root-namespace sockets; other account
rooms are unaffected. Legacy broadcasts remain unchanged when per-user mode is
off. Private-room connections also require the existing session expiry check and
an ActiveSession row matching both username and signed session_id. Missing,
expired or cleared registration rejects reconnect even if the cookie says logged_in.
Three new real test-client cases cover own-only disconnect plus revoked-cookie
replay rejection, private session counts and expired-cookie rejection. Existing
transport fixtures now create real synthetic ActiveSession records.
These tests call the notification helper after real DB revocation; they are not
full HTTP password-reset/logout tests. Continuous expiry checks for already-open
sockets, cross-process notification and Groww proxy revocation remain pending.
Restart staging to load application changes; no DB migration/frontend build.

### Private-delivery session validation

Root Socket.IO connections now keep only owner/session_id/expiry metadata in a
per-server registry, removed on disconnect. Before order/Action Center/session
count payload delivery, expired recipients and those without their matching
ActiveSession row are disconnected. Database validation errors fail closed for
that recipient. force_logout itself is sent to the owner's room before closing
it, so the non-sensitive logout message can still arrive after DB revocation.
Two actual transport tests cover already-open revoked/expired clients and another
account remaining connected. This is delivery-time validation, not an idle socket
expiry timer. It covers these account emit helpers, not every legacy direct emit,
Groww proxy transport or multiple server processes. No schema/frontend changes.

### Proxy authentication commit and order-update ownership

In per-user mode WebSocketProxy now commits user_mapping only after adapter
initialization/connection succeeds. Failed broker setup cannot grant order-update
subscription access. An already-authenticated connection must reconnect rather
than switch identity while old subscriptions remain. Order-update fan-out also
requires the client's current mapped owner to match the event owner, even if a
stale subscriber set contains another account's client id. Four tests execute
real async method bodies with fake adapters/sockets, including failed auth plus
subscription refusal, delayed identity commit and payload-owner spoof resistance.
No Groww handshake or actual proxy server runs in these tests. Ongoing API-key/
broker-token revocation on existing proxy connections remains pending; keep
restricted staging and disabled account-mode flag. No schema/frontend changes.

### Proxy fresh-auth state validation

Per-user proxy auth now verifies the presented key against the owner's current
Argon2 DB hash (not only cache) and fingerprints that hash plus decrypted broker
token and broker name. Only the fingerprint is retained per connection/adapter.
Same-token re-encryption preserves the fingerprint. Adapter credentials changing
forces the cached adapter rebuild; auth-state changes during setup refuse binding.
Protected outgoing messages and mapped incoming actions re-read auth state via
asyncio.to_thread. Missing/revoked auth, removed keys/users or rotation closes that
socket before delivery/action; normal socket teardown cleans resources and stamps.
Eight tests use real SQLite auth/key rows plus fake proxy sockets and cover exact
owner verification, revocation/rotation, stable re-encryption and action/delivery
refusal with another owner unaffected. No real proxy/Groww handshake is tested.
Every protected send incurs DB validation; throughput/load and connection setup/
teardown races still require integration verification. Idle clients close on their
next action/delivery, not a periodic sweep. No DB schema/frontend changes. Keep
restricted staging active and account-mode flag off.

### Proxy setup cleanup

Per-account authentication now keeps the original client socket identity across
credential reads and refuses to commit a disconnected or replaced socket.
Adapters created by an unsuccessful setup are disconnected in a finally block;
a shared adapter already adopted by another authenticated socket is retained.
These fake-adapter method tests cover failed initialization, credential changes,
socket removal during the final read, successful setup, and another socket
adopting the adapter. They do not verify a live broker handshake or certify all
concurrent setup, connection-pool, and teardown behavior.

### Account market-data delivery

With per-user Groww enabled, the Groww adapter wraps ticks with its own account
identity. The proxy drops unwrapped/malformed ticks and sends valid ticks only
to subscribed sockets mapped to that owner. Client payload owner fields do not
select the publisher owner. The internal envelope is removed before delivery.
Account ticks bypass the shared MarketDataService cache; account sandbox quotes
continue through the existing account-owned REST polling path. Legacy delivery
is unchanged when the flag is off. Other broker publishers have not been
migrated and their unwrapped ticks are dropped in account mode. The ZMQ channel
remains a trusted internal process boundary, not a signed transport.
Nine synthetic tests cover envelope validation, legacy payloads and actual
listener routing for two accounts; live Groww transport and load remain untested.

### Account subscription release

In per-user mode, only another live socket belonging to the same account keeps
that account adapter's exact broker subscription alive. An unrelated account in
the global symbol index no longer suppresses broker unsubscribe. The adapter
must match the caller's mapped account before release. Failed broker acknowledgments
retain local ownership for retry; disconnect still purges the disconnected
socket and retains the other account's adapter, order subscribers and auth stamp.
Seven fake-adapter tests exercise actual release and disconnect methods, including
same-account sharing, different-account sharing, wrong adapters, failed releases,
stale socket rows and legacy behavior. Live pooled broker cleanup remains untested.

### Account subscription creation checks

The existing subscribe handler already selects the adapter through the
server's authenticated client-to-account mapping. Five additional tests execute
that handler with two independent fake adapters: same-symbol creation reaches
both adapters, supplied owner/broker fields cannot choose another adapter,
missing own adapters never fall back to another account, failed requests do not
change the other account's registry, and anonymous requests are rejected.
No subscription-handler behavior changed. These tests do not exercise the live
Groww adapter or connection-pool subscription bookkeeping.

### Python strategy execution boundary

Per-account mode now explicitly rejects the entire Python strategy blueprint
with PYTHON_ACCOUNT_ISOLATION_PENDING (503), including code, logs and SSE.
Direct process starts and background initialization/restore entry points refuse
to run; status broadcasts return before accessing shared subscriber queues.
Ownership checks reject ownerless legacy configurations in account mode.
Legacy behavior is retained with both account flags off. This is a feature guard,
not an account sandbox: uploaded Python still requires an isolated runner with
separate filesystem, credentials and process permissions before this guard can
be removed. Existing processes are not killed by enabling the flag; deploy from
a stopped staging instance with no strategy children running. Nine tests execute
entry-point bodies and HTTP guard behavior; live runner isolation is not tested.

### Flow automation boundary

Flow currently lists workflows without an account filter. Until workflow CRUD,
webhooks, triggers and delivery are migrated, per-account mode refuses the whole
Flow blueprint with FLOW_ACCOUNT_ISOLATION_PENDING (503). Direct execute_workflow
and scheduled callbacks also return before locks, database reads or broker calls.
Legacy behavior is unchanged with both account flags off. This guard does not
implement per-account Flow, stop previously executing jobs or disable every
monitor thread; use restricted staging where schedulers/adapters remain off.
Six tests execute HTTP guard and direct/scheduled entry-point bodies with no
live workflow execution. Bot configuration and notification ownership remain pending.

### Messaging bot boundary

Per-account mode rejects both complete Telegram and WhatsApp blueprints with
BOT_ACCOUNT_ISOLATION_PENDING (503), including shared configuration and user
lists. Bot startup/pairing/initialization entry points and outward notification,
alert and broadcast entry points are guarded before shared state or recipient
lookup. Thus failed API-key resolution cannot use the existing browser-session
fallback to send an account alert in this mode. Legacy behavior is unchanged
with both account flags off. This disables bots rather than implementing
account-owned bots or a new administrator permission model. Existing running
bots must be stopped before deployment; restricted staging never starts them.
Eleven synthetic tests cover HTTP guards, sync startup/pairing, order alerts,
broadcast alerts, direct WhatsApp reports and legacy HTTP behavior. Live
messaging and inbound callbacks are not tested; no external messages were sent.

### Flow ownership storage foundation

FlowWorkflow now has a nullable owner_username. Startup adds the column to old
schemas without assigning legacy rows. In account mode create_workflow requires
an explicit existing username; account-scoped list/id lookup helpers filter the
owner in SQL and reject missing/unknown owners. Legacy creation with account
flags off may still create ownerless rows, which account lookups cannot see.
Seven real SQLite tests cover cross-account reads, invalid owners, legacy rows
and repeatable additive migration. This is a storage foundation only: existing
Flow HTTP routes, updates, deletes, executions, webhook authentication, caches
and trigger monitors are not fully migrated. The Flow feature guard stays on.

### Flow CRUD ownership routing (feature still disabled)

Create/list/detail/update route bodies now derive owner from the authenticated
server account in per-account mode. Posted owner fields cannot select ownership;
other-account or ownerless IDs return 404. Only inactive workflows can be edited.
Database update/delete accept an explicit owner and filter by it when supplied.
Account deletion checks ownership but still returns 503 for the owner: legacy
scheduler/subscription cleanup has not been migrated. Existing legacy calls
without explicit owner remain for internal migration and are not safe account APIs.
The entire Flow feature guard remains enabled, so these routes are not exposed
in restricted staging. Five additional HTTP tests deliberately bypass that outer
guard and run actual route bodies against SQLite with graph validation stubbed;
they verify identity, cross-account rejection, ignored owner fields, CSRF and
anonymous rejection, as well as scoped database mutations. They do not certify
workflow graph validation, armed trigger teardown, execution or live broker calls.

### Flow subscription cleanup ownership

In account mode release_workflow_subscriptions now requires explicit
owner_username matching the workflow row before reading the registry. Each
subscription must have that captured owner and a known broker. Missing or
conflicting records are retained for repair; the current-key/session fallback
is not used. Another ownerless workflow no longer falsely suppresses account
unsubscribe. A same-owner workflow still retains its shared feed. Ten synthetic
registry tests execute real cleanup bodies, including failure/retry retention.
This is a prerequisite only: callers, scheduler/price/order-monitor cleanup and
delete orchestration are not yet migrated. Flow/deletion guards remain enabled.
No live unsubscribe transport was exercised.

### Flow trigger removal ownership

Scheduler remove_job/remove_workflow_job, price remove_alert and order-update
remove_watch now require an explicit verified workflow owner in account mode.
Raw scheduler removal accepts only canonical flow_workflow_<id> job IDs and
performs the same owner check. Validation runs before registration mutation;
strict jobstore failures still propagate. Twelve tests combine real SQLite
workflow owner lookup with fake scheduler/monitor stores and actual method bodies.
This does not verify the persistent jobstore or live monitors. Existing internal
callers have not all been migrated to pass owner_username, so Flow/deletion and
restricted-staging guards must remain enabled. Legacy removal stays available
with account flags off. Stale registrations for deleted/unowned workflows need
explicit administrative repair rather than bypassing owner verification.

### Account Flow deletion orchestration (outer guard remains)

Account delete routes now dispatch to delete_account_workflow with the verified
session owner. The service checks owner before acquiring the per-workflow run
lock, rechecks under the lock, and refuses active/running workflows. It passes
the same owner to strict scheduler removal, price/order monitor removal,
subscription release and final database deletion. Failed cleanup or remaining
subscriptions retain the workflow row and credentials for idempotent retry;
partial successful removals are not rolled back. Locks release on all paths.
Eight service tests use real owner-scoped SQLite rows with fake cleanup services.
Existing CRUD route tests deliberately stub the delete dispatcher; they do not
exercise a live HTTP-to-jobstore-to-broker deletion chain. Flow's outer feature
and restricted-staging guards remain enabled. Activation/execution and monitors
still need account migration before enabling the feature.

### Flow execution owner validation foundation

validate_flow_execution_owner checks a workflow's stored owner against the
presented current API key using a fresh database hash/broker-auth verification.
No stored-key, global-key or browser-session fallback is used. Ownerless/missing
workflows, another account's key, rotated keys and revoked broker credentials
are rejected. This currently supports Groww only. Eight tests cover fresh SQLite
credential validation and explicit guards on background/internal execution.
The validator is a foundation, not yet wired into an enabled trigger/run path.
Background and internal locked execution entry points now explicitly refuse
account-mode runs before pools, execution rows or broker calls; existing outer
Flow guards remain. This does not verify order placement or credential changes
mid-run, and no live broker request was made.

### Flow run/trigger owner routing (still blocked)

Run Now and activate route bodies now check the authenticated account's workflow
before accessing trigger services. The common _run_or_start boundary invokes the
fresh owner validator with the exact workflow ID and presented key, then still
returns FLOW_ACCOUNT_ISOLATION_PENDING for valid account credentials. Invalid
credentials return a generic owner-auth failure. Account webhooks require a
configured secret and cannot borrow a browser-session/environment API key when
the stored key is missing. Legacy fallback remains with account flags off.
Eight boundary tests exercise real route/helper bodies with validator stubs;
fresh credential validation has separate real SQLite tests. These are not a
live trigger/executor integration test. Outer Flow guards and internal execution
guards remain enabled; scheduler/monitor execution wiring remains pending.

### Background Flow trigger boundary

Scheduler callbacks and price/order monitor trigger entry points now invoke the
account owner-validation boundary before submitting any execution. Persistent
schedules with no supplied key use only their workflow row's stored key, never
a global/session fallback. Blocked monitor triggers reset the one-shot claim
instead of consuming it. Database sessions used by the boundary are removed.
Even valid account credentials still return blocked: Flow execution and graph
monitoring remain disabled. Six tests execute real entry/helper bodies with
fake monitor objects and credential boundaries; these are not live jobstore,
monitor-pool or broker integration tests. Legacy triggers bypass the new owner
check when account flags are off.

### Scheduler/monitor cleanup integration check

Three integration tests now load full production scheduler and monitor modules,
use real SQLite workflow rows and an APScheduler SQLAlchemy jobstore, and run
the actual account deletion service. They verify that Alice's job is removed
from persisted storage and both monitor registries while Bob's survive; a
wrong-owner request changes nothing; and a partial failure retains the workflow
row so a retry finishes safely. The scheduler is paused, jobs are far in the
future, and no callback executes. The event bus and broker unsubscribe boundary
are stubbed; monitor registrations are seeded directly without starting polling.
This verifies cleanup composition, not trigger activation, live broker transport
or HTTP-to-execution integration. Flow and restricted-staging guards remain on.

### Offline graph-engine integration (not production activation)

Five tests load the full Flow executor module, real graph validator, real SQLite
workflow/execution tables and fresh owner/key admission, then run a small order
graph with fake broker clients. They verify distinct keys reach distinct clients,
execution rows stay under the corresponding workflow, wrong/revoked keys do not
enter the engine, broker refusal records only the owner's failed run, and the
normal account execution guard is still present after the test context ends.
The test harness explicitly bypasses the execution block only after owner
validation and only with all broker clients replaced. This is NOT an enabled
production multi-user activation/run path. Activation routes, trigger scheduling,
mid-run revocation and live broker transport are not verified by these tests.
No runtime code or production feature flag is changed by this patch.
