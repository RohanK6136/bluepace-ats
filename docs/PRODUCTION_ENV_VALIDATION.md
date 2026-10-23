# Production Environment Validation

Run this preflight against the environment variables for the backend service **before** release or after changing deployment variables. The checker is read-only and never prints secret values.

From the `backend` directory:

```bash
APP_ENV=production python -m app.services.production_config
```

For staging, use `APP_ENV=staging`. In PowerShell:

```powershell
$env:APP_ENV = "production"
python -m app.services.production_config
```

The command exits non-zero if required configuration is missing or unsafe. It checks that:

- `APP_ENV` is explicit (`production` or `staging`) rather than relying on a development default.
- `DATABASE_URL` is configured for PostgreSQL, or SQLite has been explicitly allowed; the latter always produces a durability warning.
- `JWT_SECRET` is set, is not the known development fallback, and has at least 32 characters. Generate it with a cryptographically secure generator and store it only in the deployment secret manager.
- `ALLOWED_ORIGINS` lists exact bare origins, not wildcards or paths. Production origins must use HTTPS. Include the current public frontend origin, for example `https://bluepace-ats-frontend.vercel.app`, only if that is the domain your frontend is actually using.
- Backblaze B2 variables are either configured as a complete set (`B2_ENDPOINT`, `B2_ACCESS_KEY_ID`, `B2_SECRET_ACCESS_KEY`, `B2_BUCKET`, `B2_REGION`) or the validator warns that file persistence needs manual confirmation.

Example secure key generation (prints a new secret locally; never paste it into a chat or commit it):

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Safe rollout procedure

1. Run the checker using the deployed backend's actual environment values through your hosting provider's shell or a secure local environment. Do not export or paste secrets into logs or tickets.
2. Fix each reported error. Keep `JWT_SECRET` and `DATABASE_URL` in the host's protected environment-variable settings, not in Git.
3. Before changing the database URL, confirm the target PostgreSQL instance contains the expected data and take a verified backup as described in [PostgreSQL backup and recovery](POSTGRES_BACKUP_RECOVERY.md).
4. If changing `JWT_SECRET`, plan for existing sessions and candidate-portal links that depend on signed tokens. Do not rotate it casually.
5. Verify health/readiness, login, session refresh, upload/download, and candidate-portal links against a test account after deployment.

The backend Dockerfile now defaults to `APP_ENV=production` so missing runtime configuration fails closed rather than silently selecting development defaults. Local development containers can explicitly set `APP_ENV=development`; ensure PostgreSQL and a strong JWT secret are configured for production.

**Current verification limit:** this checker does not contact the live hosting provider or database. A passing run validates only the environment supplied to the command; it is not evidence that a live database backup or restore test has completed.
