# Private scanner and tracker deployment

The application has two independent modes: individual TA setups and momentum
baskets. Each has a model journal and an actual execution journal. PostgreSQL
stores decisions, watch items, events and ledgers; a private object bucket stores
compressed, content-addressed market inputs. The browser reads the private
service. GitHub Actions runs the headless worker independently of browser uptime.

This guide prepares deployment; creating provider resources, entering credentials,
publishing the app and enabling schedules are owner actions. No production
deployment or account-data migration is implied by checking in these files.

## Local synthetic preview

Use Python 3.13 and the pinned direct dependencies in `requirements.txt`. Start
without an active private `.streamlit/secrets.toml`; demo mode refuses any
configured `DATABASE_URL`, including a local account database:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt pytest==9.0.1
$env:DATABASE_URL = $null
$env:TRACKER_ENV = "local"
$env:TRACKER_DEMO = "1"
.venv\Scripts\python.exe -m scanner_tracker demo
.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1
```

This creates `.local/demo.db` and local synthetic input archives. `TRACKER_DEMO=1`
is permitted only with `TRACKER_ENV=local`; do not set it on either hosted
environment. Stop the local demo and clear its environment variables before
configuring a real connection. The commands below use `python` to mean the
virtual environment's Python, or the managed Python in the private worker.

`.env.example` is a configuration reference, not an automatically loaded file.
The CLI reads process environment; Streamlit also reads its server-side secrets.
Never evaluate a secret file as a shell script or paste real credentials into a
chat, command transcript, issue, workflow input or repository.

## Private storage and environment settings

Create separate staging and production Supabase projects. In each project:

1. Create a **private** Storage bucket named `tracker-inputs`. The application
   does not create it automatically. Do not enable public downloads or anonymous
   upload/read policies. The server uses the private service key for object I/O.
2. From **Connect**, copy the **Session pooler** connection string, port **5432**.
   Use `postgresql+psycopg://` and `sslmode=require`; URL-encode reserved characters
   in the database password. The transaction pooler on port 6543 is unsuitable
   for this worker's session-level advisory lock.
3. Keep the project database password and service key in the provider secret
   stores. The service key has privileged access and must remain server-side.

Supabase documents the pooling modes and SSL settings in its
[PostgreSQL connection guide](https://supabase.com/docs/guides/database/connecting-to-postgres)
and the private bucket controls in
[Storage access control](https://supabase.com/docs/guides/storage/security/access-control).

| Setting | Streamlit server | GitHub worker environment |
| --- | --- | --- |
| `TRACKER_ENV` | `staging` or `production` | Set from the selected GitHub environment |
| `DATABASE_URL` | Required, private session-pooler URL with TLS | Required environment secret |
| `SUPABASE_URL` | Required project URL | Required environment secret |
| `SUPABASE_SERVICE_KEY` | Required private service key | Required environment secret |
| `TRACKER_STORAGE_BUCKET` | `tracker-inputs` | Fixed to `tracker-inputs` in the workflow |
| `TRACKER_APP_PASSWORD_HASH` | Required owner password hash | Unneeded by the headless worker |
| `GITHUB_REPOSITORY` | `SiddhantMis/TA` | GitHub supplies its repository context |
| `GITHUB_DISPATCH_TOKEN` | Optional refresh-dispatch token | Unneeded by the worker |

Generate the additional application password hash locally:

```text
python -m scanner_tracker password-hash
```

The command asks twice using a hidden prompt and requires at least 12 characters.
Save its PBKDF2 output as `TRACKER_APP_PASSWORD_HASH`; keep the plaintext owner
password in your password manager. Use the committed
`.streamlit/secrets.toml.example` only as a placeholder template.

For optional in-app refresh, use a fine-grained GitHub token restricted to this
repository with **Actions: read and write**. Save it only in Streamlit's private
server secrets. Without it, the app links to manual workflow dispatch. The token
dispatches work; it does not grant browser access to credentials. See GitHub's
[workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).

## Staging: verify privacy before adding secrets

1. Run the validation workflow for the implementation branch. In Community
   Cloud, deploy repository `SiddhantMis/TA`, the reviewed implementation branch,
   entrypoint `app.py`, Python **3.13**, with **no private credentials**. The
   application stops at its setup/access screen before constructing a private
   service when the password hash is absent.
2. In app **Settings → Sharing → Who can view this app**, select **Only specific
   people can view this app**, with the owner as the permitted viewer. A public
   GitHub repository otherwise produces a public app by default.
3. Open the URL in a signed-out/private browser and confirm that Community
   Cloud denies access. Do this before supplying database, storage, or dispatch
   secrets. The extra application password is required after the Cloud gate.
4. Add staging values through Community Cloud's Secrets settings. Leave
   `TRACKER_DEMO` absent. Create GitHub environment **staging** and add its
   `DATABASE_URL`, `SUPABASE_URL`, and `SUPABASE_SERVICE_KEY` secrets.
5. From a private administrative environment with staging `DATABASE_URL` set,
   run `python -m scanner_tracker migrate`. Verify PostgreSQL RLS is enabled on
   every tracker table and that `anon`/`authenticated` have no table privileges
   or allow policies. Migration `0001_tracker` enables RLS and revokes these
   grants where those roles exist. The server database owner still has access.
6. Sign in to the private app. Configure positive model capitals, TA risk and
   position limits, and personal symbols. Keep actual opening positions and
   executions distinct from model settings. Test first with synthetic/manual
   staging records, including a fill import preview followed by confirmation.
7. Dispatch **Private scanner tracker EOD** on the reviewed branch with
   `environment=staging`, initially `mode=both`, `scope=personal`. Then review a
   wide/all-scope run. Confirm the expected completed session, data coverage,
   pending setup transitions, basket proposal, private archive access, and that
   model decisions did not create actual fills. Record any unavailable inputs.
8. Reboot the app and confirm its records persist. Complete the backup/restore
   rehearsal below into a separate empty private database before promotion.

GitHub's first manual dispatch requires the workflow definition to exist on the
default branch. Until that reviewed workflow has landed on `main`, run the same
`python -m scanner_tracker scan --mode both --scope personal` command from the
private staging administrative environment. Keep production scheduling disabled;
do not represent a local run as completed hosted validation. See GitHub's
[manual-dispatch requirements](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_dispatch).

Community Cloud currently permits one private app at a time. Use that one slot
for the staging preview, then replace it with the production deployment; recreate
the deployment from `main` if changing its source requires it. Verify privacy
again before adding production secrets. The relevant provider instructions are
[deploying an app](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[sharing/privacy](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app),
and [secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management).
Supabase explains the database boundary in its
[RLS guide](https://supabase.com/docs/guides/database/postgres/row-level-security).

## Worker controls

`tracker-eod.yml` has three daily UTC triggers, all evaluated through the NSE
session calendar by the worker:

| UTC | IST | Purpose |
| --- | --- | --- |
| 13:45 | 19:15 | EOD processing |
| 15:45 | 21:15 | Retry after delayed publication |
| 01:45 | 07:15 | Following-morning catch-up |

Scheduled jobs remain **off** unless repository variable
`TRACKER_SCHEDULE_ENABLED` is exactly `true`. Manual dispatch remains available
with scheduling off. GitHub runs scheduled workflows from the default branch;
this worker explicitly checks out `main`. Manual staging dispatch uses the
selected ref. Production dispatch requires `main`.

Create GitHub environment **production** with its own secrets and restrict its
deployment branches to `main`; configure a required reviewer if desired. Do not
place production credentials in repository-wide secrets accessible to staging
branches. Scheduled jobs select the production environment. Manual dispatch
defaults to staging and offers `both|ta|momentum`, `all|wide|personal`, and an
optional request ID. The app's refresh dispatch must select its own configured
environment; verify a staging refresh creates a staging job.

The worker has read-only repository permission, a 150-minute timeout, one shared
concurrency group and `cancel-in-progress: false`. The database advisory lock
also prevents overlapping workers. It writes private storage only: there is no
Git push, account-data artifact upload, Pages update, or automatic migration in
this workflow. A missing configuration or failed run preserves the prior
published decisions and is reported as a failed run. Review the private run
status for partial coverage rather than interpreting it as zero candidates.

GitHub schedules can be delayed; treat the recorded completed session as the
source of truth. See
[scheduled workflow behavior](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).
The existing legacy `eod-scan.yml` retains its original public scan behavior.

## Backup, restore and promotion

Export a private bundle before any production schema upgrade or cutover:

```text
python -m scanner_tracker backup --output .local/backups/tracker-before-upgrade.zip
```

The bundle contains tracker records and referenced compressed input archives.
It is **not encrypted**. Store an encrypted/private copy outside the repository
and outside the source database/project. The CLI refuses `docs/` and `results/`
as backup destinations. Do not attach this archive to a public Actions run.

Rehearse recovery using the appropriate target environment variables and a
separate empty database/private bucket:

```text
python -m scanner_tracker migrate
python -m scanner_tracker restore --input .local/backups/tracker-before-upgrade.zip
```

Restore refuses a database containing tracker records. It verifies input archive
checksums and the supported bundle schema; the uncompressed bundle limit is
250 MB. For larger datasets, use an explicitly tested provider-native recovery
process. Verify restored record counts, balances, execution IDs and at least one
archived input before accepting the recovery rehearsal.

Promote only reviewed code after staging and recovery checks pass. Back up the
production state, apply additive migrations from a private administrative
environment, deploy `main` into the private app slot, verify anonymous access is
blocked, and then enter production secrets. Review an explicit manual production
scan before setting `TRACKER_SCHEDULE_ENABLED=true`. Do not copy synthetic demo
records or staging account records into production. The production ledger starts
from owner-confirmed opening cash/holdings and confirmed fills.

Migration downgrade deliberately refuses destructive rollback. Recovery means
using the compatible reviewed code or restoring the private bundle into an
empty compatible database, with the worker paused until verification completes.

## Validation and operational review

The new validation workflow installs the pinned runtime plus `pytest==9.0.1`,
checks the migration twice, runs the existing regression suites and new tracker
tests, exercises Streamlit AppTest, and compiles the application. It uses
synthetic records and a disposable PostgreSQL 16 service, not provider secrets.
`DATABASE_TEST_URL` is used only with `TRACKER_ENV=test`; explicit non-TLS
connections are limited to the local test service. Hosted storage requires TLS.

Local equivalents:

```text
python -m pytest -q test_patterns.py test_momentum_portfolio.py tests
python -m compileall -q scanner_tracker migrations tests app.py
```

Historical comparisons use stored source-qualified inputs:

```text
python -m scanner_tracker replay --from YYYY-MM-DD --to YYYY-MM-DD --capital POSITIVE_INR_AMOUNT
```

Replay stores a diagnostic research report. It does not change actual execution
ledgers or promote an alternative ranking into the operational strategy. Current
constituent and available-history limitations remain visible in the report.

During operation, review last successful session, failed/partial runs, missing
bars, unresolved corporate actions, archive/database reachability, provider
storage quota and backup freshness. Keep the original decision and its revisions
when correcting a fill or adding a note. An unresolved price/entitlement gap is
unavailable data rather than an assumed execution or return.

If a worker is interrupted, inspect its private run status before retrying. A
local SQLite lock may require manual removal only after confirming its process
has stopped. PostgreSQL session locks release with their connection. Disable
`TRACKER_SCHEDULE_ENABLED` while recovering credentials, connectivity or state;
then verify a manual run before resuming schedules.

The remaining owner-only setup is provider sign-in, private resource creation,
secret entry, privacy verification, app publication and eventual production
schedule enablement. These credentials and UI changes cannot be completed by an
unconnected provider plugin or an unavailable interactive browser session.

## Optional notifications and special exchange sessions

Notifications are disabled by default. To enable strategy-event updates, set the
GitHub variable `TRACKER_NOTIFY_ENABLED=true` and the environment secret
`DISCORD_WEBHOOK_URL`. Actual account values and confirmed holdings are not
included. Successful deliveries are deduplicated; failed acknowledgements may be
retried. Notification failure never changes a recorded execution or market
decision. Delivery health is retained in the private application.

The pinned NSE calendar supplies ordinary sessions and holidays. For a special
session or a new exchange closure, set the same `TRACKER_SESSION_OVERRIDES` JSON
mapping in the app secrets and worker repository variable. Each date must name
an official NSE HTTPS `source_url`. An added session requires explicit ISO8601
`market_open` and `market_close` timestamps with an offset; a removed session
uses `closed: true`. Do not invent timings or infer a special session from one
vendor row. The worker still waits its settlement window after the approved close.

The app remains labelled as shadow operation unless the owner explicitly sets
`TRACKER_SHADOW_MODE=false` after the planned ten-session reconciliation review.
This changes the operating label, not the trading rules, and never enables broker
execution. Use the same value in the app and worker environments.

The overview reports tracked input bytes and database size against reference
free-tier limits. Supabase's dashboard is authoritative, including unreferenced
uploads and other project usage. Export before approaching a quota; no records
are silently pruned and no paid plan is activated automatically.
