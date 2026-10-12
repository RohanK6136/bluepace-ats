# Production database and storage cutover runbook

## Status and safety gate

**Do not redeploy or restart the backend before capturing the current data.** The production Railway environment was inspected on 2026-10-12:

- The `bluepace-ats` backend is configured from `RohanK6136/bluepace-ats`, root directory `backend`, region `sfo`.
- Its explicit variables do not include `DATABASE_URL`, `APP_ENV`, or `JWT_SECRET`. The current code therefore defaults to `sqlite:///./bluepace_ats.db` and the development JWT fallback unless another runtime mechanism overrides them.
- The backend has no attached persistent volume.
- No `B2_*` storage variables are configured. The storage service's fallback is `./private_uploads`, resolved from the backend working directory (normally `/app/private_uploads`).

These observations establish a risk, not a verified count of production records. No database file or resume directory was downloaded during this inspection. The backup must be collected from the **currently running deployment** before a backend deploy, restart, or volume change; the tools connected to this session do not provide shell access to that container.

### Current Railway staging note (2026-10-12)

The staged pgvector service has now been removed from pending changes without deploying it. The pending Railway patch contains only two unprovisioned, unattached volumes: `postgres-volume` (left over from the earlier template attempt) and `pgvector-volume`. There is no live database service or public database proxy. The Railway API rejects deleting these volumes because they are not provisioned yet. **Do not accept/commit the current pending patch.** In Railway's dashboard, discard the remaining pending environment changes before preparing a clean pgvector service and volume. The database template is not marked as Railway-verified, and resource cost should be checked before provisioning.

## 1. Take a verified SQLite snapshot before any redeploy

The utility at `backend/scripts/sqlite_snapshot.py` uses SQLite's online-backup API against a read-only source connection. It produces a SQLite backup and a metadata-only JSON manifest with row counts, integrity status, size, and SHA-256. It does not print row contents or modify the source database.

From a trusted workstation with the Railway CLI installed and access to this project:

1. Check out branch `hardening/sqlite-postgres-cutover-prep` locally. Do **not** deploy that branch to production just to obtain the script.
2. Copy the script into the running backend container with Railway SSH/SCP. Use the live backend domain and current project/environment shown in Railway. If necessary, register an SSH key and see [Railway SSH/SCP documentation](https://docs.railway.com/cli/ssh):
   ```sh
   scp backend/scripts/sqlite_snapshot.py bluepace-ats-production.up.railway.app@ssh.railway.com:/tmp/sqlite_snapshot.py
   ```
3. Execute the script inside that same running container:
   ```sh
   railway ssh --project b44d6f10-1c0a-4352-a2eb-c99278c5026a --service bluepace-ats --environment production -- python /tmp/sqlite_snapshot.py --database /app/bluepace_ats.db --output-dir /tmp/bluepace-backups
   ```
   The `railway ssh` command supports running one command in the service container (see [Railway SSH command examples](https://docs.railway.com/cli/ssh)). If the database file is not present at `/app/bluepace_ats.db`, stop and inspect the live process working directory and its resolved SQLAlchemy SQLite path; do not substitute an empty database or create one.
4. List the exact generated backup names:
   ```sh
   ssh bluepace-ats-production.up.railway.app@ssh.railway.com 'ls -lt /tmp/bluepace-backups'
   ```
5. Copy the **matching** backup and manifest to an access-controlled local directory (replace the placeholders with the exact names from the previous command):
   ```sh
   scp bluepace-ats-production.up.railway.app@ssh.railway.com:/tmp/bluepace-backups/bluepace-ats-<timestamp>.sqlite3 ./bluepace-ats-<timestamp>.sqlite3
   scp bluepace-ats-production.up.railway.app@ssh.railway.com:/tmp/bluepace-backups/bluepace-ats-<timestamp>.manifest.json ./bluepace-ats-<timestamp>.manifest.json
   ```
   Check the local SHA-256 against the manifest's `sha256` and `backup_size_bytes`, and retain a second encrypted copy outside Railway. Do not commit either file to GitHub or upload candidate data into chat.
6. Check the manifest's table counts, `integrity_check`, and `foreign_key_violations`. Investigate any foreign-key violations before migration.

A snapshot located only in `/tmp` is not durable. Do not proceed until the files have been copied out of the container and the local checksum matches the manifest. Register an SSH key with Railway first if `ssh`/ `scp` requests authentication; do not paste private keys into chat.

## 2. Back up resume and candidate-document files separately

The database snapshot does not back up files stored on disk. First inspect whether the directory exists and how many files it contains:
```sh
railway ssh --project b44d6f10-1c0a-4352-a2eb-c99278c5026a --service bluepace-ats --environment production -- sh -lc 'if [ -d /app/private_uploads ]; then find /app/private_uploads -type f | wc -l; else echo "NO_LOCAL_UPLOAD_DIRECTORY"; fi'
```

If the directory exists, create a private archive of the entire tree **inside the current running container**:
```sh
railway ssh --project b44d6f10-1c0a-4352-a2eb-c99278c5026a --service bluepace-ats --environment production -- sh -lc 'tar -czf /tmp/bluepace-private-uploads.tar.gz -C /app private_uploads && sha256sum /tmp/bluepace-private-uploads.tar.gz'
```
Then copy it to the same access-controlled local backup directory:
```sh
scp bluepace-ats-production.up.railway.app@ssh.railway.com:/tmp/bluepace-private-uploads.tar.gz ./bluepace-private-uploads.tar.gz
```
Verify the archive checksum locally against the checksum printed inside Railway. Keep the folder structure intact and encrypt the local backup. If local files are absent, record that result rather than creating a directory or empty archive. If database references use `b2://`, verify those referenced objects and B2 credentials separately; don't assume a SQLite backup includes these objects. Never print file contents or tokens in logs.

Do not configure a new storage provider or change `RESUME_STORAGE_DIR` before existing files and database references have been reconciled.

## 3. Provision an isolated PostgreSQL target

No PostgreSQL database service is currently provisioned or staged. The previous staged service was removed without deployment; only two unattached staged volumes remain until the pending patch is discarded in Railway Dashboard. After backup, create or select an approved PostgreSQL service that supports pgvector. The `pgvector-pg18` template is not marked as verified by Railway; review its source and expected resource usage before approving it. Do not point the live backend at a new database yet.

The application's PostgreSQL setup requires the `vector` extension because embedding columns use pgvector. Verify the target supports `CREATE EXTENSION vector`. Keep the database on the Railway private network where possible and do not expose a public TCP proxy just for migration.

For a workstation-based migration, prefer Railway's SSH tunnel rather than enabling a public TCP proxy. After a clean database service has been provisioned, run `railway connect pgvector --tunnel-only --environment production` and keep that command running. Use its localhost-forwarded connection details as the target URL in a second terminal, stored in `MIGRATION_TARGET_DATABASE_URL` through a secure environment/secret workflow. The Railway CLI documents that `--tunnel-only` opens an SSH tunnel without needing a public proxy. If the service name differs, select the actual pgvector service name.

## 4. Test migration on a copy, not production

Once the verified snapshot and matching manifest have been copied to a trusted workstation, use the migration utility added at backend/scripts/migrate_sqlite_to_postgres.py. Run it from the backend directory with the same Python environment as the app. Put the approved PostgreSQL connection string into MIGRATION_TARGET_DATABASE_URL through a secure environment/secret manager; do not hard-code it in scripts or commit it to Git.

First, run read-only preflight. This checks the snapshot checksum, SQLite integrity, foreign-key integrity, table/column mapping, pgvector availability and that the target has no public tables. It does not create tables or change the target:

    cd backend
    APP_ENV=test python scripts/migrate_sqlite_to_postgres.py --source /secure/path/bluepace-ats-<timestamp>.sqlite3 --manifest /secure/path/bluepace-ats-<timestamp>.manifest.json

Only after reviewing the preflight report and confirming the destination is the intended, empty, non-production test database should a migration be applied:

    APP_ENV=test python scripts/migrate_sqlite_to_postgres.py --source /secure/path/bluepace-ats-<timestamp>.sqlite3 --manifest /secure/path/bluepace-ats-<timestamp>.manifest.json --apply --confirm-empty-target

The tool refuses to merge into an existing populated destination and checks table row counts in the migration transaction. If it aborts because of unmapped data, missing required fields or a foreign-key problem, do not patch around the check on production; investigate and update the migration mapping, then rerun against a fresh empty target.

For a quick, metadata-only review of the saved manifest (no candidate row data is displayed), run:
```sh
python -c "import json; p='bluepace-ats-<timestamp>.manifest.json'; d=json.load(open(p, encoding='utf-8')); print(json.dumps({k:d[k] for k in ('backup_file','backup_size_bytes','sha256','integrity_check','foreign_key_violations','tables','total_rows')}, indent=2))"
```
The checksum of the local snapshot can be recalculated with `sha256sum bluepace-ats-<timestamp>.sqlite3` on Linux/macOS or `Get-FileHash .\\bluepace-ats-<timestamp>.sqlite3 -Algorithm SHA256` in PowerShell. Compare it with the manifest before preflight.

Before cutover:

- Create a target database that has no application data in it.
- Migrate a verified copy of the SQLite backup to PostgreSQL. Validate table coverage, row counts, foreign-key integrity, identity/sequence values, timestamp values, JSON fields, and vector embeddings. Stop if any source table with data has no destination mapping.
- Run the backend test suite and targeted API checks against the migrated target; verify admin login, recruiter login, organizations, jobs, candidates, applications, interviews, documents, offers, and candidate portal behavior.
- Compare representative records without copying personal data into CI logs.
- Test application startup and readiness using the intended production variables in a non-production environment.

The migration must be repeatable and must refuse to overwrite a non-empty target. Do not connect the live backend to an unverified target.

## 5. Plan the production cutover

Schedule a short maintenance window. Rehearse rollback first. During cutover, stop write traffic, capture a final consistent SQLite snapshot and file archive, migrate the final snapshot, verify counts and integrity again, and only then switch the backend database configuration.

Set `DATABASE_URL`, `APP_ENV=production`, and a cryptographically random `JWT_SECRET` together. Verify readiness before reopening writes. Don't set only `APP_ENV=production`: the current code correctly rejects SQLite in a non-development environment and requires a configured JWT secret.

For `DATABASE_URL`, use the Railway private reference to the approved database service (for example, `${{pgvector.DATABASE_URL}}`, adjusting the service name as needed) instead of putting a public database URL into code. Generate the new JWT secret locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and enter it directly in Railway's backend Variables UI as a secret; do not commit it, paste it into chat, or add it to logs. Only apply all three variables after the migrated target is approved and the production cutover window is underway.

**Session impact:** switching away from the publicly known development JWT fallback invalidates existing access tokens and candidate-portal tokens signed with that fallback. Plan recruiter re-login and regeneration/resending of candidate-portal links. Do not retain the known development secret as a compatibility fallback.

## 6. Post-cutover verification and rollback

- Confirm `/healthz` and `/readyz` succeed, with production security headers.
- Check database-backed routes and verify a harmless create/read/update/delete cycle with a test record in the correct organization.
- Check resume/document downloads for both local references and any configured object storage references.
- Compare migrated row counts with the signed-off manifest and verify PostgreSQL foreign keys and sequences.
- Keep the original SQLite snapshot and file archive encrypted and access-restricted through the agreed rollback window. Do not delete the source container artifacts until the backup is verified off-platform.
- Do not roll back the code to SQLite after the application has accepted new PostgreSQL writes unless a reverse data-sync plan is ready; otherwise recent records would be lost.

## Provider cost note

The staged `pgvector-pg18` template is not marked as verified by Railway. Railway's current Free plan offers $1/month of resource credit, while the Hobby plan has a $5 monthly minimum; actual resource usage can exceed included credits. Do not assume a database is free merely because the service can be created. A Supabase Free project is an alternative for non-critical/testing workloads (500 MB database quota) but can pause after 7 days of low activity and does not include downloadable platform backups, so it should not be treated as a complete production-backup strategy. Check the live plan and billing dashboard before provisioning.
