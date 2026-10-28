# Cloudflare Pages deployment fallback

BluePace ATS has a Direct Upload Cloudflare Pages project named `bluepace-ats-frontend`. Its Git integration is currently unavailable, so production uploads are handled by GitHub Actions + Wrangler rather than Cloudflare's Git integration.

## One-time setup

1. In Cloudflare, open **My Profile → API Tokens** and create a custom token scoped to the account that owns the Pages project. Grant **Account → Cloudflare Pages → Edit** only. Do not use a Global API Key.
2. In GitHub, open the repository **Settings → Secrets and variables → Actions → New repository secret**.
3. Create a secret named `CLOUDFLARE_API_TOKEN` and paste the token value there. The workflow already pins the non-secret Cloudflare Account ID, so no account-ID secret is needed.
4. Do not paste the token into source files, commit it, or send it in chat.

## Deploy the latest main branch

1. Open **Actions → Deploy frontend to Cloudflare Pages**.
2. Click **Run workflow** and select the `main` branch. Production deployment is intentionally manual so that only deliberate releases publish to the public site.
3. The workflow runs frontend linting, server/bulk-match/JD-match API tests, and the production build before upload.
4. After upload, it smoke-tests the Pages home page, `/v1/models`, the built-in rules engine, JD standardization, rubric generation, and resume evidence matching.
5. Treat the deployment as successful only if the workflow finishes green, including all production smoke tests.

Production Pages URL: https://bluepace-ats-frontend.pages.dev

## Scope and limitations

- This workflow bypasses Vercel's daily deployment quota for the Cloudflare Pages site.
- The Vercel URL `https://bluepace-ats-frontend.vercel.app` remains a separate deployment and is not changed by a Cloudflare upload.
- The smoke tests use the built-in rules engine; they do **not** prove that OpenRouter inference works. Real AI inference must be tested separately with a valid provider key.
- The workflow stops before publishing if `CLOUDFLARE_API_TOKEN` is absent or if it is run from a branch other than `main`.
- Production deployments are serialized so a second run cannot cancel a deployment already in progress.
