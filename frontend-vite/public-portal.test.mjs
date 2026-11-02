import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const workspace = await readFile(new URL("./src/AtsWorkspace.jsx", import.meta.url), "utf8");
const brandStyles = await readFile(new URL("./src/brand.css", import.meta.url), "utf8");
const helpCenter = await readFile(new URL("./src/PublicHelpCenter.jsx", import.meta.url), "utf8");
const statusPage = await readFile(new URL("./src/PublicStatusPage.jsx", import.meta.url), "utf8");

test("public careers portal exposes the persisted accessible light/dark theme toggle", () => {
  assert.match(workspace, /<ThemeToggle theme=\{theme\} onToggle=\{toggleTheme\} \/>/);
  assert.match(workspace, /aria-pressed=\{theme === "dark"\}/);
  assert.match(workspace, /localStorage\.setItem\("bluepace_theme", theme\)/);
  assert.match(brandStyles, /html\.dark \.bp-public-shell/);
});

test("public job search exposes every supported API filter", () => {
  for (const id of ["public-role-search", "public-department", "public-location", "public-work-mode"]) {
    assert.ok(workspace.includes('id="' + id + '"'), "missing public filter: " + id);
  }
  for (const field of ["search", "department", "location", "work_mode"]) {
    assert.ok(workspace.includes("publicFilters." + field), "missing filter binding: " + field);
  }
  assert.match(workspace, /"\/public\/jobs"/);
});

test("public portal renders live job data and useful candidate guidance without fabricated vacancies", () => {
  assert.match(workspace, /publicJobs\.map\(\(job\) =>/);
  assert.match(workspace, /Open roles/);
  assert.match(workspace, /View full role description/);
  assert.match(workspace, /A clear path from application to outcome/);
  assert.match(workspace, /PDF or DOCX files up to 5 MB/);
  assert.doesNotMatch(workspace, /Senior Software Engineer - Sample|Demo vacancy|Sample opening/i);
});

test("public portal light and dark styles cover the added content sections", () => {
  for (const selector of [
    ".bp-careers-stats",
    ".bp-application-steps",
    ".bp-public-checklist",
    ".bp-public-help-strip",
    "html.dark .bp-careers-stats",
    "html.dark .bp-application-step",
    "html.dark .bp-checklist-items",
  ]) {
    assert.ok(brandStyles.includes(selector), "missing theme style: " + selector);
  }
});

test("public vacancy results are paginated from the runtime ATS API", () => {
  assert.match(workspace, /params\.limit = PUBLIC_JOBS_PAGE_SIZE/);
  assert.match(workspace, /params\.offset = publicOffset/);
  assert.match(workspace, /Load more roles/);
  assert.match(workspace, /setPublicJobs\(\(current\) =>/);
  assert.match(workspace, /page\.length === PUBLIC_JOBS_PAGE_SIZE/);
});

test("a public ATS API failure is never presented as a genuine empty vacancy list", () => {
  assert.match(workspace, /if \(!Array\.isArray\(response\.data\)\)/);
  assert.match(workspace, /We could not load current vacancies/);
  assert.match(workspace, /Retry loading vacancies/);
  assert.match(workspace, /setPublicError\(errorText\(requestError\)\)/);
  assert.match(workspace, /No open positions are available right now/);
  assert.match(workspace, /!publicLoading && !publicError && publicJobs\.length === 0/);
});

test("public help copy matches the enforced 5 MB PDF/DOCX resume limit", () => {
  assert.match(helpCenter, /PDF and DOCX resumes up to 5 MB/);
  assert.doesNotMatch(helpCenter, /10\s?MB/i);
});

test("production HTML exposes the source commit for live release verification", async () => {
  const viteConfig = await readFile(new URL("./vite.config.js", import.meta.url), "utf8");
  assert.match(viteConfig, /VERCEL_GIT_COMMIT_SHA/);
  assert.match(viteConfig, /GITHUB_SHA/);
  assert.match(viteConfig, /name="bluepace-build-commit"/);
  assert.match(viteConfig, /"unknown"/);
});

test("public status route is wired for production verification", () => {
  assert.match(workspace, /import PublicStatusPage from "\.\/PublicStatusPage\.jsx"/);
  assert.match(workspace, /window\.location\.pathname === "\/status"/);
  assert.match(workspace, /window\.location\.pathname === "\/status\/"/);
  assert.match(workspace, /<PublicStatusPage apiUrl=\{API_URL\} theme=\{theme\} onToggleTheme=\{toggleTheme\} \/>/);
  assert.match(statusPage, /\/public\/jobs\?limit=1&offset=0/);
  assert.match(statusPage, /bluepace-build-commit/);
  assert.match(statusPage, /An empty array is valid when no genuine open roles are published/);
});
