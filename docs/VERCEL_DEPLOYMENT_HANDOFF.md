# Vercel deployment handoff

## Verified repository state

- Repository: `RohanK6136/bluepace-ats`
- Production branch: `main`
- Frontend path: `frontend-vite/`
- Existing deployment workflow: `.github/workflows/deploy-vercel.yml`
- Existing workflow expects GitHub Actions repository secret `VERCEL_TOKEN`.
- The workflow pins Vercel organization/team ID `team_Rjt1DblVvXgrkIwTZ9t91a9L` and project ID `prj_DpQbpA1dF1LtdcPyxBMAHEiZU1fy`.

## Blocker found during this run

The available Vercel connection could list a team and project names but could not resolve the existing project under the listed team scope. Attempting to create/link a project returned HTTP 403 permission denied. No deployment was created by this run.

## Safe next actions

1. In GitHub, open **Settings → Secrets and variables → Actions** for this repository.
2. Confirm that repository secret `VERCEL_TOKEN` exists and is scoped to an account/team that has access to the Vercel project.
3. In the Vercel dashboard, confirm the team and project IDs match the identifiers pinned in `.github/workflows/deploy-vercel.yml`.
4. Trigger the **Deploy frontend to Vercel** workflow using **Actions → Deploy frontend to Vercel → Run workflow**. Do not report success unless the workflow is green and a deployment URL is returned.
5. After a successful deploy, smoke-test the public frontend, login, API connectivity, and critical job/candidate workflows.

## Important distinction

This note records what was observed during a deployment attempt; it does not claim that production has been deployed or verified. It does not include secrets or tokens.
