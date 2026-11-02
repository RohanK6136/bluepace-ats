# BluePace production deploy path

This is the operator handbook for the public careers frontend. It exists so the next incident is noticed in hours, not weeks.

## Ownership

| Concern | Where |
| --- | --- |
| GitHub repo | `RohanK6136/bluepace-ats` |
| Frontend project | Vercel project `bluepace-ats-frontend` (`prj_DpQbpA1dF1LtdcPyxBMAHEiZU1fy`) |
| Team | Vercel team `team_Rjt1DblVvXgrkIwTZ9t91a9L` |
| Production alias | https://bluepace-ats-frontend.vercel.app |
| Public status page | https://bluepace-ats-frontend.vercel.app/status |
| ATS API | https://bluepace-ats-11.onrender.com |
| Frontend root directory | `frontend-vite` |
| Production branch | `main` |

Who can change production: anyone with Vercel access to the team above, plus write access to the GitHub repo. Prefer merges to `main` over ad-hoc CLI deploys.

## How deploys trigger

1. Merge a PR into `main`.
2. Vercel's Git integration builds `frontend-vite` and promotes a **production** deployment when the commit is on `main`.
3. Preview deployments are created for non-`main` branches. Previews are not production.
4. Manual redeploy is available via the GitHub Action `Deploy frontend to Vercel` (`workflow_dispatch` only). It requires the `VERCEL_TOKEN` repository secret. Do not run it in a loop; the Hobby plan has a rolling 100-deployments/24h limit.

Required Vercel environment variable:

- `VITE_API_URL=https://bluepace-ats-11.onrender.com` (production, preview, development)

## Verify a deploy is actually live

Dashboard green is not enough. Confirm all of the following:

1. **HTTP 200** on https://bluepace-ats-frontend.vercel.app/
2. **Commit evidence** in the live HTML:
   - Inspect page source for `<meta name="bluepace-build-commit" content="…">`
   - The value must equal the 40-character Git SHA of the intended `main` commit (or `unknown` only on local/dev builds)
3. **Status page** at `/status` reports ATS API, database readiness, public vacancies feed, and backend deployment identity
4. **Vacancies feed**:
   - `GET https://bluepace-ats-11.onrender.com/public/jobs?limit=1&offset=0` returns HTTP 200 and a JSON array
   - An empty array is valid when no roles are published
   - 4xx/5xx or non-array JSON is a failure, never an empty careers list

Cache-bypass tip: append a unique query string (for example `?v=<sha>`) when checking HTML commit identity.

## Vacancies rules (non-negotiable)

- Jobs are fetched at **runtime** from `/public/jobs` (paginated). Publishing a job in the ATS must appear without a frontend redeploy.
- **API error ≠ empty list.** If the feed fails, the UI must show an explicit error + retry + contact link. Only a successful empty array may show "No open positions are available right now."
- No hardcoded or demo vacancies in the public careers UI.
- Filter and paginate only real published ATS jobs.

## Automated guards

| Guard | Workflow / surface |
| --- | --- |
| Daily production health + vacancies reachability + frontend commit match | `.github/workflows/production-availability.yml` (cron + push to `main`) |
| Failure alert | Opens/updates a single GitHub issue titled `[Production Alert] BluePace public careers and ATS health` |
| Manual production redeploy + smoke | `.github/workflows/deploy-vercel.yml` |
| Static portal regression tests | `frontend-vite/public-portal.test.mjs` |

After every merge to `main`, wait for a Vercel production deployment, then confirm the live commit meta matches `main`. The scheduled health job fails loudly if they diverge.

## Incident order of operations

1. Hunt **one root cause** before treating two symptoms (permissions / billing before rate limits).
2. Confirm production is serving the intended SHA by content evidence, not only the Vercel dashboard.
3. Confirm vacancies distinguish error vs empty.
4. Open or update the single production alert issue if the health workflow fails.
