# Frontend npm dependency audit

**Audit date:** 2026-10-23  
**Scope:** `frontend-vite/package-lock.json`

## Remediation applied

The committed lockfile was refreshed with compatible, non-major updates using npm's audit fixer. Confirmed patched versions now include:

| Package | Locked version after remediation | Finding addressed |
|---|---:|---|
| `vite` | 8.3.5 | Vite security advisories affecting 8.3.0–8.3.2; 8.3.3 is the published patch baseline. |
| `follow-redirects` | 1.16.1 | Cross-origin redirect credential stripping and sensitive-header handling advisories affecting 1.16.0. |
| `source-map-js` | 1.2.2 | Indexed source-map offset denial-of-service advisory affecting versions before 1.2.2. |
| `postcss-selector-parser` | 6.1.5 | The 6.x security backport for quadratic flat-selector parsing. npm's current advisory range still flags this version, so this remains visible in the full report until advisory metadata confirms the backport. |

References: [Vite GHSA-9jrq-w75r-8gcw](https://github.com/vitejs/vite/security/advisories/GHSA-9jrq-w75r-8gcw), [follow-redirects GHSA-q3jh-wrc6-jgq8](https://github.com/advisories/GHSA-q3jh-wrc6-jgq8), [source-map-js GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q), and [postcss-selector-parser GHSA-rj75-hqrm-r3gf](https://github.com/advisories/GHSA-rj75-hqrm-r3gf).

## Remaining full-audit findings

After compatible lockfile updates, the full npm audit still reports seven entries (five high, two moderate). They are all classified as development/build-tool dependencies in the current lockfile:

- `braces`, `chokidar`, and `micromatch` are connected to GHSA-vfj7-8cjw-p6xm, a deeply nested pattern stack-exhaustion issue. The advisory currently lists no patched `braces` release. It is not appropriate to invent a patched version or force a major framework downgrade to make the report appear clean.
- `tailwindcss` remains on 3.4.19. npm offers Tailwind CSS 4.3.3 as the broad remediation, which is a major upgrade and needs a separate, visual/regression-tested migration before it can be adopted safely.
- `fast-glob` and `postcss-nested` remain in the full report; preserve the complete npm audit output in CI and re-evaluate when compatible upstream fixes are available.

Reference for the unresolved `braces` advisory: [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).

## CI policy

CI prints the full dependency advisory report so development dependencies remain visible, and separately runs:

```sh
npm audit --omit=dev --audit-level=moderate
```

This production-dependency check currently passes with **zero reported production vulnerabilities**. Build and server tests also pass after the lockfile refresh. The full dev-tooling report is intentionally not represented as clean; Tailwind CSS 4 migration and the unpatched upstream advisory remain follow-up work.

Do not use `npm audit fix --force` as a substitute for a reviewed major-version migration.
