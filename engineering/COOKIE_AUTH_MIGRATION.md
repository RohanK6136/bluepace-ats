# Browser session security rollout

## What changed

The React ATS workspace now uses the browser session endpoints under `/auth/session`.
The access token is set only in an HttpOnly cookie; it is not returned to browser JavaScript
or stored in local/session storage. The backend still accepts Bearer tokens for existing
API clients and integrations.

- `POST /auth/session/login`: verifies credentials and sets the access and CSRF cookies.
- `POST /auth/session/refresh`: rotates the persisted session token and resets both cookies.
- `POST /auth/session/logout`: revokes the current persisted session and clears both cookies.
- Unsafe requests carrying the browser access cookie require an allowed `Origin` plus a
  matching `bluepace_csrf` cookie and `X-CSRF-Token` header.
- Session responses are marked `Cache-Control: no-store`.

## Production configuration

Set these on the **backend service only**:

- `JWT_SECRET`: a strong, randomly generated secret. Coordinate any rotation because it
  invalidates existing recruiter sessions and candidate portal links signed by the same key.
- `AUTH_COOKIE_SECURE=true`: required for HTTPS production.
- `AUTH_COOKIE_SAMESITE=none`: use for the cross-site Vercel/Railway frontend/backend
  pairing. The backend enforces Secure when SameSite=None is requested.
- `ALLOWED_ORIGINS`: comma-separated exact frontend origins, for example
  `https://bluepace-frontend-production.up.railway.app,https://bluepace-ats-frontend.vercel.app`.
  Include only origins actually used by the deployment; do not include paths or wildcards.

Do not put `JWT_SECRET`, provider API keys, or OAuth client secrets in Vite variables.
The frontend needs no access-token secret: the browser sends the HttpOnly cookie through
credentialed requests.

## Verification checklist

1. Confirm the frontend production origin is present in backend `ALLOWED_ORIGINS`.
2. Sign in and verify the access cookie has `HttpOnly`, `Secure`, and an appropriate
   SameSite policy in browser developer tools. The access token must not appear in
   Local Storage, Session Storage, API response JSON, or JavaScript logs.
3. Confirm an authenticated write without `X-CSRF-Token` fails with HTTP 403.
4. Confirm a write with the matching CSRF cookie/header succeeds.
5. Confirm refresh rotates the persisted session, logout revokes it, and a subsequent
   protected request is rejected.
6. Run backend and frontend CI, then verify against the deployed backend before enabling
   this as production-complete.

## Compatibility and rollback

Legacy `/auth/token`, `/auth/refresh`, and `/auth/logout` Bearer endpoints remain for
non-browser clients. To roll back the React client, revert the frontend commit and redeploy;
do not weaken CSRF checks or expose the cookie token to JavaScript as a rollback shortcut.
