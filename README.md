# Snowflake Postgres Mirror Hands-On Lab

> Replicate an operational Snowflake Postgres database into Snowflake continuously, with one procedure call and no ETL.

> **Based on the Snowflake quickstart _"Mirror Data from Snowflake Postgres to Snowflake"_.**
> This lab reimplements the IoT mirroring quickstart:
> - Guide: <https://www.snowflake.com/en/developers/guides/snowflake-postgres-mirror-to-snowflake/>
> - Source: <https://github.com/Snowflake-Labs/sfquickstarts/blob/master/site/sfguides/src/snowflake-postgres-mirror-to-snowflake/snowflake-postgres-mirror-to-snowflake.md>
>
> It keeps the same use case and data model (IoT devices, sensors, and readings) and the
> same learning path. It replaces the guide's copy-and-paste steps with a [Task](https://taskfile.dev/)
> workflow in which every lab step changes Postgres and then **waits until Snowflake has caught
> up**, printing a timeline as it goes. It also adds mirror operations, a load generator, and
> analytics on the mirrored data. See
> [Relationship to the Snowflake Quickstart](#relationship-to-the-snowflake-quickstart) for a full diff.

## Overview

Snowflake Postgres **data mirroring** keeps Snowflake tables in sync with Postgres tables using change data capture (CDC). One call to `SNOWFLAKE.POSTGRES.CREATE_MIRROR` creates:

- **In Postgres:** a publication, a logical replication slot, and a CDC worker that writes change logs to Iceberg tables through `pg_lake`
- **In Snowflake:** a target database with one table per source table, plus `<table>$changes` (a 7-day change feed) and `<table>$live` (a low-latency view), and a serverless apply task

This lab automates the setup with Task:

- **Postgres instance:** create one (default) or use one you already own, routed by `POSTGRES_INSTANCE_MODE`
- **Secure connection setup:** credentials go to `~/.pgpass` (mode 600) and are never displayed. A `POSTGRES_INGRESS` network policy is scoped to your IP, and connections use `sslmode=verify-ca`.
- **Snowflake objects as code:** the lab database, warehouse, analyst role, network policy, and step 7 analytics are declared in two DCM (Database Change Management) projects, deployed and purged as a whole
- **Seven lab steps:** each runs SQL in Postgres, waits for the mirror, and shows the Snowflake side
- **Companion notebook:** generated from a template and uploaded to a personal Snowflake Workspace (`USER$.PUBLIC.<DEMO_NOTEBOOK_NAME>`) as a Notebook in Workspaces, for the Snowflake-side exploration
- **Extras:** a `psql` load generator, mirror operations (`ALTER`/`SUSPEND`/`RESUME`/`REFRESH`), and a dynamic table, semantic view, and Cortex Agent on the mirrored data

## Quick Start

```bash
# 1. Configure environment
cp .env/mirror.env.template .env/mirror.env
# Edit .env/mirror.env: set CLI_CONNECTION_NAME (and review the defaults)

# 2. Provision Postgres, seed the IoT tables, deploy the notebook (~5-10 minutes)
task demo-up

# 3. Work through the lab (or run all steps: task step-all)
task step-1-create-mirror
task step-2-add-data
task step-3-schema-changes
task step-4-deletes
task step-5-live-and-changes
task step-6-operate-mirror      # extra: operate the mirror
task step-7-analytics           # extra: build on the mirrored data

# 4. Clean up
task demo-teardown
```

Open the notebook URL that `demo-up` prints in Snowsight and keep it next to your terminal: the terminal changes Postgres, and the notebook explores the same change in Snowflake. The first time you run it, Snowsight asks you to connect the notebook to a notebook service (it runs on Container Runtime; SQL still uses the lab warehouse).

### How It Routes

`demo-up` and `demo-teardown` dispatch on `POSTGRES_INSTANCE_MODE`:

| | `create` (default) | `existing` |
|---|---|---|
| **demo-up** | Deploys the DCM project `iot_mirror_lab` (lab objects plus a `POSTGRES_INGRESS` network policy for your IP), grants `postgres_mirror_admin`, and creates a new `STANDARD_M` instance (`STANDARD_L` on Azure). Saves the connection without displaying secrets. Ends with a readiness checklist. | Deploys `iot_mirror_lab` (lab objects only), grants `postgres_mirror_admin`, and checks an instance you already own: READY (resumed if suspended) and owned by `MIRROR_ADMIN_ROLE_NAME`. Saves its service entry. Never touches its network policy. Ends with a readiness checklist. |
| **demo-teardown** | Purges both DCM projects (lab objects, network policy, the warehouse if the lab owns it), and drops the mirror, the **instance**, the local connection entries, and the notebook workspace | Purges both DCM projects, and drops the mirror, the notebook workspace, and **only the tables this lab created**. Keeps your instance and connection. |

Override the mode for a single run from your shell:

```bash
POSTGRES_INSTANCE_MODE=existing task demo-up
```

## Prerequisites

- [Task](https://taskfile.dev/): task runner (install: `brew install go-task`)
- [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli) (`snow`) **3.17 or later** (DCM projects, `snow dcm purge`) with a configured connection
- [psql](https://www.postgresql.org/docs/current/app-psql.html) 16 or later (install: `brew install libpq && brew link --force libpq`)
- [Python 3.9+](https://www.python.org/): the helper scripts use only the standard library (no venv or `pip install`)
- A Snowflake account on **AWS or Azure** with Snowflake Postgres available, and a role that can create Postgres instances, network policies, roles, and DCM projects (`ACCOUNTADMIN` by default)

**Use non-interactive authentication.** The lab runs many `snow` commands. Key-pair, PAT, or password connections work without prompting. A browser-SSO connection opens a browser for every command unless token caching is enabled.

### Validate Prerequisites

```bash
task validate-prerequisites
```

This checks the env file (required variables, plus the format of every name that ends up in SQL), `snow` and its connection, `psql` 16+, and Python 3.9+.

## Configuration

Copy the template and edit `.env/mirror.env` (git-ignored). It is the single source of truth for the Snowflake SQL, the Postgres SQL, the helper scripts, and the notebook.

```bash
cp .env/mirror.env.template .env/mirror.env
```

Use a different env file by setting `DOTENV_FILENAME`:

```bash
DOTENV_FILENAME=other.env task demo-up
```

#### Snowflake

```bash
CLI_CONNECTION_NAME=my_connection         # snow connection used by every task
MIRROR_ADMIN_ROLE_NAME=ACCOUNTADMIN       # creates/owns the instance, network policy, and mirror
DEMO_WAREHOUSE_NAME=IOT_MIRROR_LAB_WH
DEMO_WAREHOUSE_MANAGED=true               # true: DCM creates and teardown drops it; false: use an existing warehouse as-is
DEMO_DATABASE_NAME=POSTGRES_MIRROR_HOL    # lab-owned objects (network rule, notebook, analytics)
DEMO_SCHEMA_NAME=LAB
DEMO_ANALYST_ROLE_NAME=IOT_MIRROR_ANALYST # gets read access to the mirrored data in step 1
```

#### DCM Projects

```bash
DCM_PROJECT_DATABASE=UTIL                 # where the DCM project objects live (created if missing, kept on teardown)
DCM_PROJECT_SCHEMA=DCM_PROJECT_ARCHIVE
DCM_SETUP_PROJECT_NAME=IOT_MIRROR_LAB     # setup objects (tasks/snow-cli/dcm/iot_mirror_lab)
DCM_ANALYTICS_PROJECT_NAME=IOT_MIRROR_ANALYTICS  # step 7 analytics (tasks/snow-cli/dcm/iot_mirror_analytics)
```

#### Postgres Instance

```bash
POSTGRES_INSTANCE_MODE=create             # create | existing
PG_INSTANCE_NAME=IOT_MIRROR_LAB           # exact, case-sensitive instance name
PG_COMPUTE_FAMILY=STANDARD_M              # create mode; AWS-only, use STANDARD_L on Azure; BURST_* is not supported
PG_STORAGE_SIZE_GB=10
PG_POSTGRES_VERSION=                      # create mode; empty = platform default, or pin a major version (e.g. 18)
PG_DATABASE_NAME=postgres
PG_SCHEMA_NAME=public
PG_SERVICE_NAME=iot_mirror_lab            # entry in ~/.pg_service.conf
PG_ALLOWED_CIDR=AUTO                      # AUTO = your current IP/32; ranges wider than /8 are refused
```

#### Mirror

```bash
MIRROR_NAME=iot_mirror                    # lowercase (mirror names fold to lowercase)
MIRROR_TARGET_DATABASE_NAME=IOT_MIRROR_DB_01  # must not exist; can NEVER be reused
MIRROR_REFRESH_INTERVAL='1 minute'        # '30 seconds' | '1 minute' | '10 minutes' | '1 hour' | '1 day'
MIRROR_TARGET_TABLE_TYPE=SNOWFLAKE        # SNOWFLAKE | ICEBERG
```

> **Target database names can never be reused**, even after the mirror and the database are dropped. Bump the suffix (`_01` → `_02`) before every new mirror. Step 1 checks this and stops with a clear message.

The template also covers the step 7 object names, verification timeouts (`LAB_SYNC_TIMEOUT_SECONDS`, `LAB_POLL_INTERVAL_SECONDS`), and the load generator (`STREAM_*`).

## Lab Walkthrough

Every step prints the SQL it runs. Each step that changes data then waits for Snowflake, printing a timeline like this (from step 2):

```text
Waiting for IOT_MIRROR_DB_01.PUBLIC.READINGS to match Postgres (refresh interval 1 minute, timeout 300s)
  elapsed   postgres  snowflake    $live
  [   0s]        985        485      485
  [  23s]        985        485      985   ← $live already has the change; the target table catches up on the next apply
  [  68s]        985        985      985   ✓ target table matches Postgres
```

The exact timings depend on the refresh interval and when the next apply run starts. The `postgres` column is the source of truth, `snowflake` is the target table, and `$live` is the low-latency view.

### Setup: `task demo-up`

Deploys the DCM project `iot_mirror_lab`: the lab database, schema and stage, the warehouse (when `DEMO_WAREHOUSE_MANAGED=true`), the analyst role and its grants, and in create mode the `POSTGRES_INGRESS` network rule and policy, with your current IP filled in. It then grants the `snowflake.postgres_mirror_admin` application role to `MIRROR_ADMIN_ROLE_NAME` (as `ACCOUNTADMIN`, skipped if the role already holds it). The grant runs first because on a new account the `snowflake` application can take up to an hour to appear, and that is better found before the session than during it. If you can't use `ACCOUNTADMIN`, setup prints the `GRANT` for an admin to run.

It then provisions the instance (typically 3-5 minutes in create mode), and creates and seeds the operational IoT schema from the quickstart: **5 devices, 10 sensors, 485 readings**. Every table has a primary key, so updates and deletes replicate. Re-running `demo-up` is safe: the seed only runs on empty tables.

Setup ends with a readiness checklist. Every row should read `PASS` before step 1; anything else comes with the fix. Run it again any time with `task setup-status`:

```text
Setup status
  Warehouse IOT_MIRROR_LAB_WH                               PASS
  Lab schema POSTGRES_MIRROR_HOL.LAB                        PASS
  Stage POSTGRES_MIRROR_HOL.LAB.LAB_STAGE                   PASS
  Analyst role IOT_MIRROR_ANALYST                           PASS
  ACCOUNTADMIN holds snowflake.postgres_mirror_admin        PASS
  Postgres instance IOT_MIRROR_LAB READY and owned by ...   PASS
  Network policy IOT_MIRROR_LAB_PG_INGRESS_POLICY attached  PASS
  Ingress rule allows your IP (or PG_ALLOWED_CIDR)          PASS
  Postgres login (psql "service=iot_mirror_lab")            PASS
  Postgres hostname                                         INFO  <host>
  Postgres password                                         INFO  Saved for snowflake_admin in ~/.pgpass (mode 600); ...
```

> **One password to care about.** Creating an instance returns credentials for two Postgres users: `snowflake_admin` and an application role. The lab uses only `snowflake_admin`, saves that password to `~/.pgpass`, and never displays it. Lost or rotated elsewhere? `task pg-reset-access`.

### Step 1: Create the mirror (`task step-1-create-mirror`)

1. **Pre-flight (Postgres):** the source tables must be ordinary, `LOGGED`, and have a primary key, with types that map cleanly to Snowflake.
2. **Grant (Snowflake):** `GRANT USAGE ON POSTGRES INSTANCE ... TO APPLICATION snowflake`, run as the owning role. (The `postgres_mirror_admin` application role was granted during setup.)
3. **Pre-flight (Snowflake):** your role holds `postgres_mirror_admin`, the instance is READY and owned by your role (mirror procedures require ownership), and the target database doesn't exist yet.
4. **`CALL SNOWFLAKE.POSTGRES.CREATE_MIRROR(...)`**: see [`002-create_mirror.sql`](tasks/snow-cli/sql/mirror/002-create_mirror.sql).
5. **Initial snapshot:** waits until every table moves from `SNAPSHOTTING` to `REPLICATING`.
6. **Confirm:** counts match in Snowflake (5 / 10 / 485). The analyst role gets read access through the `<TARGET>_ADMIN` database role.
7. **Look inside Postgres:** the `snowflake_cdc` and `pg_lake` extensions, the publication, the replication slot, and the change-log tables, all created for you. You never ran `CREATE EXTENSION`.

### Step 2: Add more data (`task step-2-add-data`)

Inserts 500 readings spread over the last 24 hours (985 total). `READINGS$live` shows them within about 30 seconds; `READINGS` follows on the next apply run.

### Step 3: Schema changes (`task step-3-schema-changes`)

`ALTER TABLE devices ADD COLUMN status TEXT` (populated with an `UPDATE`, because mirrored tables don't allow `ADD COLUMN ... DEFAULT`), then `RENAME COLUMN location TO site_location`. Snowflake shows `STATUS` and `SITE_LOCATION` without any mirror reconfiguration. A column change starts a fresh `DEVICES$changes` feed.

### Step 4: Deletes (`task step-4-deletes`)

Deletes readings older than 12 hours. The rows leave `READINGS` on the next apply, and `READINGS$changes` keeps a record of them as `_CHANGE_TYPE = 'D'` rows.

### Step 5: `$live` and `$changes` (`task step-5-live-and-changes`)

Inserts `IoT-Gateway-Urgent` and puts `IoT-Gateway-1` into maintenance. `DEVICES$live` shows both before `DEVICES` is updated. In `DEVICES$changes` the update appears as a delete/insert pair sharing one `_XID`.

> `$live` is **not transactional**: it can expose part of a source transaction. Use the target tables when you need consistency.

### Step 6: Operate the mirror (`task step-6-operate-mirror`)

- `ALTER_MIRROR(refresh_interval => '30 seconds')`
- Creates a new Postgres table, `maintenance_events`. It is **not** mirrored until `ALTER_MIRROR(add_tables => [...])`, because the mirror uses table-level scope. It then takes its own initial snapshot.
- `SUSPEND_MIRROR`, then 100 inserts in Postgres. The step observes the counts for 90 seconds: Postgres keeps capturing changes while apply is paused, and the target table doesn't move.
- `RESUME_MIRROR` plus `REFRESH_MIRROR`: the target table catches up.
- Restores the refresh interval and shows the monitoring views (`DESCRIBE_MIRROR`, `QUERY_ADMIN_LOG`, apply task history).

### Step 7: Analytics on mirrored data (`task step-7-analytics`)

Mirrored tables are ordinary Snowflake tables with change tracking on, so you can build on them directly. The dynamic table and semantic view are the DCM project `iot_mirror_analytics`, deployed here rather than during setup because they read the mirror's target database (step 1) and the columns step 3 adds. The agent is created with SQL afterwards, because DCM does not manage agents.

- **Dynamic table** `SITE_HOURLY_METRICS`: hourly metrics per site and sensor type (end-to-end freshness = refresh interval + `TARGET_LAG`)
- **Semantic view** `IOT_MIRROR_SV`: dimensions and metrics for Cortex Analyst
- **Cortex Agent** `IOT_MIRROR_AGENT`: ask questions in Snowsight under **AI & ML > Agents**, e.g. *"Which site had the highest average temperature in the last 12 hours?"* (Enterprise edition)

### Anytime: watch it stream (`task stream-readings`)

A pure-`psql` load generator: every `STREAM_INTERVAL_SECONDS` it inserts `STREAM_BATCH_SIZE` readings and updates one, for `STREAM_BATCHES` batches (using `\watch`). Watch the counts climb in the notebook's section 2. Don't run steps 2 or 4 while it streams, because their checks wait for row counts to match.

```bash
task stream-readings                                # defaults: 60 batches x 20 readings every 5s
STREAM_BATCHES=12 STREAM_BATCH_SIZE=50 task stream-readings
```

## Available Tasks

### Main Tasks

| Task | Description |
|------|-------------|
| `task demo-up` | Provisions Postgres (routes by `POSTGRES_INSTANCE_MODE`), seeds the IoT tables, and deploys the notebook |
| `task step-1-create-mirror` … `task step-7-analytics` | The lab steps, in order |
| `task step-all` | Runs steps 1 through 7 (presenter dry run / smoke test) |
| `task demo-teardown` | Tears everything down (routes by `POSTGRES_INSTANCE_MODE`; asks to confirm, `task --yes demo-teardown` skips the prompt) |

### Utilities

| Task | Description |
|------|-------------|
| `task validate-prerequisites` | Checks the env file, `snow` and its connection, `psql` 16+, and Python 3.9+ |
| `task infrastructure-up` | Provisions the instance and lab objects only, then runs the readiness checklist |
| `task setup-status` | Readiness checklist: PASS / FAIL / INFO for every setup object, with a fix for each |
| `task setup-plan` | What DCM would create, alter, or drop for the setup objects (`iot_mirror_lab`); applies nothing |
| `task analytics-plan` | The same for the step 7 analytics (`iot_mirror_analytics`; needs steps 1 and 3) |
| `task dcm-analyze` | Validates both DCM projects' definitions; applies nothing |
| `task mirror-status` | Mirror health: status, apply lag, errors, per-table state, recent apply runs |
| `task compare` | Row counts in Postgres, the target tables, and the `$live` views |
| `task mirror-refresh` | Applies pending changes now (`REFRESH_MIRROR`) |
| `task mirror-resume` | Resumes a suspended mirror (for example after an interrupted step 6) |
| `task stream-readings` | Load generator (see above) |
| `task pg-shell` | Interactive `psql` on the lab database |
| `task pg-instance-info` | Instance state, owner, size, and host (never credentials) |
| `task pg-allow-my-ip` | Create mode: redeploys `iot_mirror_lab` so the ingress rule allows your current IP (new Wi-Fi, VPN) |
| `task pg-reset-access` | Rotates the Postgres password into `~/.pgpass` (asks to confirm) |

Once `demo-up` has run, `psql "service=iot_mirror_lab"` works from anywhere.

## Architecture

```text
 Your laptop                         Snowflake account (AWS or Azure)
 ───────────                         ──────────────────────────────────────────────────────────────
                                     ┌────────────────────────────────────────────────────────────┐
 task lab-N ──psql (5432, TLS)──────►│ Snowflake Postgres instance  IOT_MIRROR_LAB                │
   ~/.pg_service.conf                │   network policy: POSTGRES_INGRESS rule = your IP/32       │
   ~/.pgpass (600)                   │                                                            │
                                     │   public.devices / sensors / readings   (your OLTP data)   │
                                     │        │ WAL                                               │
                                     │        ▼                                                   │
                                     │   publication + logical replication slot   (iot_mirror)    │
                                     │        │ snowflake_cdc worker, ~every 15s                  │
                                     │        ▼                                                   │
                                     │   pg_lake ─► Iceberg change logs + metalog                 │
                                     └────────────────────────┬───────────────────────────────────┘
                                                              │ auto-refresh (~30s)
                                     ┌────────────────────────▼───────────────────────────────────┐
 task lab-N ──snow CLI──────────────►│ IOT_MIRROR_DB_01  (created and owned by CREATE_MIRROR)     │
                                     │   PUBLIC.READINGS$changes   7-day change feed (Iceberg)    │
                                     │   PUBLIC.READINGS$live      target + pending changes       │
                                     │   PUBLIC.READINGS           target table ◄── apply task    │
                                     │        (same for DEVICES, SENSORS)    APPLY_MIRROR_IOT_... │
                                     │                                       serverless, every    │
                                     │                                       refresh_interval     │
                                     └────────────────────────┬───────────────────────────────────┘
                                                              │ change tracking
                                     ┌────────────────────────▼───────────────────────────────────┐
 Snowsight ─────────────────────────►│ POSTGRES_MIRROR_HOL.LAB   (lab-owned)                      │
                                     │   DCM iot_mirror_lab:  stage · ingress network rule        │
                                     │   DCM iot_mirror_analytics:  SITE_HOURLY_METRICS (dynamic  │
                                     │     table) · IOT_MIRROR_SV (semantic view)                 │
                                     │   SQL:  notebook · IOT_MIRROR_AGENT                        │
                                     └────────────────────────────────────────────────────────────┘
```

## Repository Structure

```text
snowflake-postgres-hol/
+-- Taskfile.yml                       # Main tasks (routes by POSTGRES_INSTANCE_MODE)
+-- .env/
|   +-- mirror.env.template            # Configuration template
|   +-- mirror.env                     # Your config (git-ignored)
+-- tasks/
|   +-- validate-prerequisites/        # env file, snow 3.17+ + connection, psql 16+, Python 3.9+
|   +-- snow-cli/                      # Everything that runs against Snowflake
|   |   +-- snowcli-tasks.yml
|   |   +-- snowflake.yml              # Defaults for optional <% ctx.env.X %> placeholders
|   |   +-- cmd/                       # Notebook generate scripts
|   |   +-- dcm/                       # DCM projects: manifest.yml + sources/definitions/*.sql
|   |   |   +-- iot_mirror_lab/        # Setup: lab DB/schema/stage, warehouse, analyst role, ingress policy
|   |   |   +-- iot_mirror_analytics/  # step 7: dynamic table, semantic view, analyst grants
|   |   +-- pyutil/
|   |   |   +-- dcm/                   # Runs snow dcm with the identifier and -D variables from .env
|   |   |   +-- snowclisp/             # Runs NNN-*.sql files in order with snow
|   |   |   +-- pginstance/            # Instance lifecycle; writes ~/.pgpass, never prints secrets
|   |   |   +-- notebook/              # Uploads the notebook to its workspace; prints its URL; drops it
|   |   +-- sql/
|   |   |   +-- init/                  # Home schema for the DCM project objects
|   |   |   +-- mirror/                # 001 grants, 002 CREATE_MIRROR, 003 analyst read access
|   |   |   +-- lab/                   # Snowflake-side query for each lab step
|   |   |   +-- ops/                   # step 6: ALTER / SUSPEND / RESUME / REFRESH, monitoring
|   |   |   +-- analytics/             # step 7: Cortex Agent and its grant (not a DCM object type)
|   |   +-- notebook/mirror_lab_notebook/
|   |       +-- templates/             # Notebook template
|   |       +-- variables.json         # Placeholder -> env var mapping
|   |       +-- generated/             # Rendered notebook (git-ignored)
|   +-- psql-cli/                      # Everything that runs against Postgres
|   |   +-- psqlcli-tasks.yml
|   |   +-- pyutil/psqlclisp/          # psql twin of snowclisp (fills psql variables from env)
|   |   +-- sql/
|   |       +-- setup/                 # 001 tables, 002 seed (5/10/485), 003 verify
|   |       +-- lab/                   # Postgres-side change for each lab step
|   |       +-- inspect/               # Pre-flight checks; what CREATE_MIRROR built in Postgres
|   |       +-- ops/                   # step 6 Postgres changes
|   |       +-- stream/                # \watch load generator
|   |       +-- teardown/              # Drops only tables this lab created
|   +-- lab/
|       +-- lab-tasks.yml
|       +-- pyutil/mirrorcheck/        # Polls both sides, prints convergence timelines; setup checklist
+-- output/                            # Scratch output (git-ignored)
+-- README.md
```

## How It Works

- **One env file, four consumers.** Task loads `.env/mirror.env` into the environment. Snowflake SQL reads it through `snow` templating (`<% ctx.env.MIRROR_NAME %>`), the DCM definitions through Jinja variables (`{{ lab_database }}`) that `pyutil/dcm/dcm.py` passes with `-D`, Postgres SQL through psql variables (`:"pg_schema"`, filled in by `psqlclisp.py`), and the notebook generator through `variables.json`. A missing required variable fails with "SQL rendering error" instead of running SQL against a placeholder.
- **Declarative Snowflake objects.** The two DCM projects declare the desired state with `DEFINE` (`DEFINE DATABASE`, `DEFINE ROLE`, `DEFINE NETWORK RULE`, ...). A deploy creates, alters, or leaves each object as needed, so re-running setup converges instead of failing, and `snow dcm purge` drops exactly what a project manages. What DCM cannot manage stays as SQL: the Postgres instance, the mirror and its grants, and the Cortex Agent.
- **Ordered SQL batches.** `snowclisp.py` and `psqlclisp.py` run `NNN-*.sql` files in numeric order and stop on the first error.
- **Self-verifying steps.** `mirror_check.py` reads Postgres with `psql` and Snowflake with `snow`, and polls until the change is visible (counts, columns, table states) or `LAB_SYNC_TIMEOUT_SECONDS` expires.
- **Re-runnable.** DCM deploys converge, setup seeds only empty tables, step 3 skips DDL that already happened, step 1 skips `CREATE_MIRROR` if the mirror exists, and teardown tolerates partial state.

## Security

1. **Credentials are never displayed.** `CREATE POSTGRES INSTANCE` and `RESET ACCESS` return passwords. `pg_instance.py` captures that output in memory and writes only your `snowflake_admin` password to `~/.pgpass` (mode 600, editing its own line only). Errors are redacted.
2. **Verified TLS.** The instance CA certificate is saved to `~/.snowflake/postgres/certs/<service>.pem`, and connections use `sslmode=verify-ca`.
3. **Least network exposure.** The `POSTGRES_INGRESS` rule allows a single `/32` by default, and ranges wider than `/8` are refused. It applies only to the Postgres instance, not to Snowflake logins.
4. **Least privilege for readers.** Analysts read mirrored data through the `<TARGET>_ADMIN` database role, without owning anything.
5. **Roles.** Everything runs as `MIRROR_ADMIN_ROLE_NAME` (`ACCOUNTADMIN` by default) to keep the lab short. In production, own databases, warehouses, and the instance with `SYSADMIN` (or a custom role granted to it), use functional roles like the analyst role for day-to-day work, and reserve `ACCOUNTADMIN` for account-level setup such as network policies and the `postgres_mirror_admin` grant.
6. **Safe on shared instances.** In existing mode the lab refuses to adopt same-named tables it didn't create, and teardown drops only the tables it created (no `CASCADE`).
7. **Never commit `.env/mirror.env`** (it is git-ignored). It holds names, not secrets.

## Cost and Cleanup

- **Postgres instance:** billed while it runs (compute plus storage). `STANDARD_M` is the smallest family that supports mirroring on AWS; on Azure it is `STANDARD_L`.
- **Mirror apply task:** serverless compute on every apply run. A shorter `refresh_interval` costs more; `$live` gives low-latency reads without shortening it.
- **Storage:** the change logs live on the Postgres instance, and the target tables in Snowflake.

Run `task demo-teardown` when you finish. Teardown order matters and is handled for you: `iot_mirror_analytics` is purged before `iot_mirror_lab` (it reads its schema), the mirror is dropped before the instance, and the instance before `iot_mirror_lab` purges the network policy attached to it. The warehouse is dropped only when `DEMO_WAREHOUSE_MANAGED=true`; with `false`, DCM never defines it, so an existing warehouse is safe. The DCM project home (`UTIL.DCM_PROJECT_ARCHIVE`) is left in place.

## Troubleshooting

| Issue | Solution |
|-------|----------|
| **Task not found** | Install Task: `brew install go-task` |
| **`Snowflake CLI ... is too old`** | DCM needs `snow` 3.17 or later: `snow upgrade` (direct install), or reinstall from the Snowflake CLI docs |
| **`snow dcm deploy failed`** | Run `task setup-plan` (or `task analytics-plan`) and read `tasks/snow-cli/dcm/<project>/out/plan_result.json`; `task dcm-analyze` lists definition errors |
| **`analytics-plan` / step 7 fails on missing columns or database** | `iot_mirror_analytics` reads the mirror (step 1) and `SITE_LOCATION` / `STATUS` (step 3): run those first |
| **`psql` not found** | `brew install libpq && brew link --force libpq` |
| **`Env file not found`** | `cp .env/mirror.env.template .env/mirror.env` |
| **`SQL rendering error`** | A required variable is missing from `.env/mirror.env`; run `task validate-prerequisites` |
| **psql times out connecting** | Your IP changed: `task pg-allow-my-ip`. If Snowflake sees a different IP than Postgres will (proxy or VPN split), set `PG_ALLOWED_CIDR` |
| **Password authentication failed** | `task pg-reset-access` (rotates the password into `~/.pgpass`) |
| **`Target database ... already exists` / name reuse** | Names can never be reused: bump `MIRROR_TARGET_DATABASE_NAME`, then re-run the step |
| **`permission denied to create extension` on `CREATE_MIRROR`** | The instance predates mirroring. Refresh it in Snowsight (Postgres → instance → Manage); there is no SQL for this. New instances don't need it. |
| **`Application role 'SNOWFLAKE.POSTGRES_MIRROR_ADMIN' does not exist`** | New accounts can take up to an hour to provision the `snowflake` application |
| **Mirror procedures fail on an existing instance** | The caller must **own** the instance: set `MIRROR_ADMIN_ROLE_NAME` to the owning role |
| **`Could not grant postgres_mirror_admin`** | Your user can't use `ACCOUNTADMIN`: have an account admin run the printed `GRANT APPLICATION ROLE ...`, then re-run `task infrastructure-up` |
| **`setup-status` shows FAIL or WAIT** | Each row prints its fix. `WAIT` on the instance means it is still provisioning: run `task setup-status` again in a minute |
| **`PG_COMPUTE_FAMILY=STANDARD_M is not available on Azure`** | Set `PG_COMPUTE_FAMILY=STANDARD_L` and re-run `demo-up` |
| **A step times out waiting** | `task mirror-status` for errors and lag; `task mirror-refresh` to apply now; or raise `LAB_SYNC_TIMEOUT_SECONDS` |
| **Mirror left suspended (step 6 interrupted)** | `task mirror-resume` |
| **`cannot alter column type` on a mirrored table** | Column type changes aren't supported on mirrored tables; add a new column and migrate the data instead |
| **Cortex Agent: model not available in your region** | `ALTER ACCOUNT SET CORTEX_ENABLED_CROSS_REGION = 'ANY_REGION';` |
| **Browser opens for every command** | Use a key-pair, PAT, or password `snow` connection, or enable token caching |

Deeper diagnostics:

```bash
task mirror-status                       # status, lag, last error, per-table state, apply runs
task pg-shell                            # then: SELECT * FROM snowflake_cdc.snapshot_status;
```

## Using Cortex Code with the Lab

The lab saves its Postgres connection in the standard `~/.pg_service.conf` / `~/.pgpass` layout used by [Cortex Code](https://docs.snowflake.com/en/user-guide/cortex-code/cortex-code)'s built-in Postgres skill, so you can ask it about the lab in natural language:

- *"List my mirrors"* or *"check the status of iot_mirror"*
- *"Show me the last 20 changes from READINGS$changes"*
- *"Run a health check on my iot_mirror_lab Postgres connection"*
- *"My mirror is failing, help me debug it"*

## Relationship to the Snowflake Quickstart

### Same as the quickstart

- The IoT schema and seed data: `devices`, `sensors`, `readings` (5 / 10 / 485 rows), plus the 500-row insert (985)
- The learning path: create the mirror → confirm the data → add data → schema changes (`ADD COLUMN status`, `RENAME location TO site_location`) → deletes → `$live` and `$changes` → cleanup
- Grants (`postgres_mirror_admin`, instance `USAGE` for the `snowflake` application) and a `1 minute` refresh interval

### How this lab differs

| Area | Quickstart | This lab |
|------|------------|----------|
| Orchestration | Copy and paste between Snowsight and `psql` | [Task](https://taskfile.dev/) workflow, ordered SQL files, `.env/mirror.env` |
| Postgres instance | Created by hand in Snowsight | Created by `demo-up` (or bring your own with `POSTGRES_INSTANCE_MODE=existing`) |
| Credentials | `psql postgres://<user>:<password>@...` | `~/.pgpass` (mode 600) plus `sslmode=verify-ca`; passwords are never displayed |
| Network access | Not covered | `POSTGRES_INGRESS` network policy for your IP, plus `task pg-allow-my-ip` |
| Extensions | `CREATE EXTENSION snowflake_cdc CASCADE` | No manual step: per the docs, new instances include the required extensions and `CREATE_MIRROR` provisions the rest. Step 1 shows what it built. |
| Verification | "Wait about a minute, then check" | Each step polls both sides and asserts convergence, printing a Postgres / target / `$live` timeline |
| Re-runs | Not covered | Pre-flight checks, the target-database reuse rule, DCM deploys that converge, idempotent teardown |
| Snowflake objects | Created by hand | Two DCM projects (`iot_mirror_lab`, `iot_mirror_analytics`), deployed and purged by the tasks |
| Teardown | `DROP_MIRROR('iot_mirror', TRUE)` + `DROP POSTGRES INSTANCE` | Same order, with the named argument `drop_target_database => TRUE`, plus `snow dcm purge` of both projects and the local connection entries |

### Feature coverage matrix

**Demonstrated (parity with the quickstart):**

| Capability | Where |
|------------|-------|
| `CREATE_MIRROR` with table-level scope | `sql/mirror/002-create_mirror.sql` |
| Initial snapshot (`SNAPSHOTTING` → `REPLICATING`) | Step 1 (`mirror_check.py wait-replicating`) |
| Ongoing inserts | Step 2 |
| Schema evolution (add / rename column) | Step 3 |
| Delete replication | Step 4 |
| `$live` low-latency reads and the `$changes` 7-day feed | Step 5, notebook sections 2–5 |
| `DROP_MIRROR` with `drop_target_database` | `task demo-teardown` |

**Added beyond the quickstart:**

| Capability | Where |
|------------|-------|
| Automated instance, network policy, and secure connection setup | `demo-up` (`pg_instance.py`, DCM `iot_mirror_lab/sources/definitions/network.sql`) |
| Snowflake objects managed as DCM projects (`DEFINE`, plan, deploy, purge) | `tasks/snow-cli/dcm/`, `task setup-plan` |
| Postgres-side view of the mirror (publication, slot, change logs) | Step 1 (`psql-cli/sql/inspect/mirror_objects.sql`) |
| Update pairs in `$changes` (`_XID`, `_IS_UPDATE`) | Step 5 |
| `ALTER_MIRROR` (refresh interval, `add_tables`), `SUSPEND` / `RESUME` / `REFRESH_MIRROR` | Step 6 |
| Monitoring: `DESCRIBE_MIRROR`, `QUERY_ADMIN_LOG`, apply task history | Step 6, `task mirror-status` |
| Read-access delegation with the `<TARGET>_ADMIN` database role | Step 1, notebook section 8 |
| Continuous load generator | `task stream-readings` |
| Dynamic table, semantic view (DCM), and Cortex Agent on mirrored data | Step 7 |
| Iceberg target tables | `MIRROR_TARGET_TABLE_TYPE=ICEBERG` |

**Beyond both the guide and this lab:**

| Capability | Notes |
|------------|-------|
| Schema-level scope (`postgres_schemas`) | New tables in a mirrored schema are picked up automatically |
| Iceberg targets on your own storage (`external_volume`) | Requires an external volume granted to the `snowflake` application |
| Pinning apply to a user-managed warehouse (`warehouse`) | Serverless is the default |
| `RESTART_MIRROR` (soft/hard re-snapshot) | Rebuilds `$changes` from a fresh baseline |
| Health and lag alerts on `DESCRIBE_MIRROR` | See *Alert on mirror health* in the docs |

## Resources

- [Mirror Data from Snowflake Postgres to Snowflake (quickstart)](https://www.snowflake.com/en/developers/guides/snowflake-postgres-mirror-to-snowflake/): the guide this lab is based on
- [Data mirroring](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring): how mirroring works, costs, transactional guarantees
- [Create a mirror](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-create) · [Query mirrored data](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-query) · [Manage and monitor mirrors](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-manage)
- [Mirror procedures reference](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-reference) · [Troubleshoot mirrors](https://docs.snowflake.com/en/user-guide/snowflake-postgres/postgres-data-mirroring-troubleshooting)
- [Snowflake Postgres instance management](https://docs.snowflake.com/en/user-guide/snowflake-postgres/managing-instances)
- [Task documentation](https://taskfile.dev/) · [Snowflake CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli)

## License

This project is provided as-is for educational and demonstration purposes.
