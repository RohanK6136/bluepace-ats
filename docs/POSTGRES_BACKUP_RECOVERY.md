# BluePace ATS PostgreSQL backup and recovery runbook

This runbook describes how to back up and test recovery for the backend database. It does not connect to, alter, or create a backup of any live database. Schedule and execute the commands using an authorized database operator and the production provider's dashboard/credentials.

## 1. Pre-flight persistence checks

Before relying on a database, confirm in the hosting provider's dashboard that `DATABASE_URL` points to the intended managed PostgreSQL database (not an ephemeral filesystem or a local SQLite file). Keep the URL private and never print it in CI logs, support messages, or a shell transcript.

With a PostgreSQL client configured for the same database, run:

```sql
SELECT current_database(), current_user, pg_is_in_recovery();
SELECT count(*) AS organizations FROM organizations;
SELECT count(*) AS users FROM users;
SELECT count(*) AS jobs FROM jobs;
SELECT count(*) AS candidates FROM candidates;
SELECT count(*) AS applications FROM applications;
```

Record the database provider, instance/cluster identifier, configured backup retention, point-in-time recovery (PITR) window, and the timestamp of the check in the team's private operations log. A successful `/readyz` response only checks that the API can execute a trivial SQL query; it does **not** prove that a provider has backups enabled or that a restore has been tested.

## 2. Portable logical backup

Prefer the database provider's managed snapshot/PITR feature for operational recovery, and additionally take a portable `pg_dump` before risky schema or release changes. Run this on a trusted operator machine with `postgresql-client` installed; do not run it in a web request or commit a dump to Git.

Configure `PGHOST`, `PGPORT` (normally 5432), `PGDATABASE`, `PGUSER`, and `PGSSLMODE=require` from the provider's connection details. Put the password in a protected `.pgpass` file or use the organization's approved secret manager; do not put credentials directly in command arguments or commit them. `pg_dump` accepts standard libpq connection settings; do not pass the SQLAlchemy-specific `postgresql+psycopg://` URL unchanged.

```sh
set -eu
umask 077
export PGSSLMODE=require
BACKUP_DIR="${BACKUP_DIR:-$HOME/bluepace-db-backups}"
mkdir -p "$BACKUP_DIR"
BACKUP_FILE="$BACKUP_DIR/bluepace_$(date -u +%Y%m%dT%H%M%SZ).dump"

pg_dump --format=custom --no-owner --no-acl --file="$BACKUP_FILE"
pg_restore --list "$BACKUP_FILE" >/dev/null
sha256sum "$BACKUP_FILE"
printf 'Backup archive validated: %s\n' "$BACKUP_FILE"
```

Copy the archive to an access-controlled, encrypted backup location separate from the database provider/account where feasible. Keep the SHA-256 checksum and backup timestamp beside the archive, not the database password. Apply a documented retention schedule and confirm that the backup is decryptable by the designated recovery operators.

## 3. Restore drill — isolated database only

Run restore tests on a new, empty, isolated PostgreSQL database or temporary clone, never directly against production. Confirm that the target has the required PostgreSQL extensions available (BluePace enables `vector` during database initialization; the provider must support `pgvector`).

```sh
set -eu
export PGSSLMODE=require
# Set PGHOST / PGPORT / PGUSER and credentials for the isolated restore target.
# Set RESTORE_DATABASE to the target database name, not the production database.
createdb "$RESTORE_DATABASE"
pg_restore --no-owner --no-acl --dbname="$RESTORE_DATABASE" "$BACKUP_FILE"
```

If extension privileges or ownership cause restore errors, follow the database provider's documented process to provision extensions and restore into a fresh target. Do not resolve restore errors by granting superuser rights to the running ATS application.

After restoration, verify the expected core tables exist, compare table row counts with the pre-backup inventory, and exercise API reads against the isolated restore. Run the backend regression suite with `APP_ENV=test` against test-only fixtures; do not point destructive tests at production. Check important relationships such as candidate/application/job linkage and the `auth_sessions` table. Record restore duration, any missing data, and follow-up actions.

## 4. Recovery procedure

1. Declare the incident and pause writes or put the application into a maintenance window.
2. Choose the correct managed snapshot/PITR timestamp and verify the recovery target with the database owner.
3. Restore to a new database/instance first. Validate schema, core table counts, login, session revocation, candidate access, and document references.
4. Update the backend's secret-managed `DATABASE_URL` only after verification; keep the existing instance until the recovered system passes smoke tests.
5. Restart the backend and verify `/healthz` and `/readyz`, then perform a supervised read/write smoke test. Watch application logs for migration failures.
6. Record the recovered point in time, estimated lost-write window, operator, and final result. Keep the source instance/backup for rollback until the incident owner approves cleanup.

## 5. Session and signing-key precautions

- Access-token validity depends on a JWT signature, a non-empty `jti`, and a matching unexpired, non-revoked `auth_sessions` row. Backups should include `auth_sessions` consistently with the user tables.
- Never rotate `JWT_SECRET` casually. A rotation can invalidate recruiter sessions and candidate portal links signed by the previous key. Inventory impact and coordinate a planned change before updating the secret.
- A restored database may contain still-valid sessions. Restrict restore targets, logs, and access accordingly, and only cut over after security review.
- This repository's API container and the Vercel frontend are separate deployment concerns. Deploying the frontend to Vercel does not back up or deploy the FastAPI database/runtime.
