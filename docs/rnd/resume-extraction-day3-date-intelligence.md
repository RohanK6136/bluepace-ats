# BluePace ATS — Resume Extraction Intelligence (Day 3)

**Scope:** Employment timeline normalisation in the deterministic resume extractor  
**Base:** \`main\`  
**Change branch:** \`feature/resume-extraction-date-intelligence\`  
**Status:** Implementation in review; automated CI pending

## 1. Problem identified

The prior experience-duration helper only recognised a limited \`YYYY - YYYY\` / \`YYYY - Present\` shape. It did not retain month-level precision and summed each employment entry independently. Consequently:

- Month-level dates could be reduced to year-only estimates.
- Concurrent roles could be counted twice.
- Only the first date range in an employment duration string was considered.
- Future end dates were not bounded to the current reference month.

These issues affect the derived \`years_of_experience\` value and the downstream review signal that compares explicit and date-derived experience.

## 2. Implementation

The extractor now recognises:

- Month names and abbreviations (for example, \`Jan 2020\`, \`January 2020\`, \`May'20\`).
- Numeric month/year formats (for example, \`05/2020\`).
- Year/month formats (for example, \`2020/05\`).
- Year-only ranges (for example, \`2020 - 2022\`).
- Current-employment terms (\`Present\`, \`Current\`, \`Now\`).
- Multiple explicit ranges in one duration string.

Intervals are normalised to calendar months and merged before summing. This avoids double-counting overlapping or adjacent roles. Future end dates are bounded to the reference month, and future start dates are not included.

## 3. Conservative date semantics

- An explicit month-specific end date is included as a stated employment month.
- A year-only end date is treated as an exclusive boundary at the start of that year. This avoids assuming the candidate worked through the full end year when the resume only provides a year.
- \`Present\`, \`Current\` and \`Now\` are exclusive boundaries at the start of the current reference month. The incomplete current month is not added.
- Invalid, reversed, incomplete and future-only ranges do not produce an experience estimate.
- The result is rounded to one decimal year; it is an extraction estimate, not a verified employment fact.

The existing explicit-years statement remains preferred by the extractor when present. Existing consistency review signals remain in place to flag a material difference between the explicit value and the date-derived estimate.

## 4. Regression coverage added

A deterministic unit-test file covers:

- Month-name and abbreviated-month dates.
- Numeric month/year and year/month dates.
- Year-only ranges.
- Present/current end dates with a fixed reference date.
- Multiple ranges in one duration.
- Overlapping and separate employment intervals.
- Future end-date bounding.
- Missing, reversed and future-only dates.
- Non-dictionary experience entries.

The tests use synthetic strings and a fixed reference date. They are unit/regression coverage, not a measured accuracy benchmark on real CVs.

## 5. Remaining benchmark work

A representative, consented/de-identified gold set is still required before reporting extraction precision, recall, F1, or production accuracy. It should include text PDFs, DOCX files with tables, multi-column layouts, scanned/image-only PDFs, different date conventions, overlapping roles, gaps, and missing fields.

Future evaluation should separately measure:

- Employment title/company/date field accuracy.
- Date-range normalisation and overlap handling.
- Unsupported/inferred field rate.
- Source-evidence support for each extracted field.
- Extraction success rate and p50/p95 processing latency by document type and engine.

No OCR, Docling configuration, AI provider, database schema, storage policy, upload limit, or production deployment setting is changed by this implementation.

## 6. Acceptance status

- [x] Inspect existing experience extraction and confidence/review logic.
- [x] Support common month-level and year-level employment date formats.
- [x] Avoid double-counting overlapping employment intervals.
- [x] Bound future employment end dates and omit future-only ranges.
- [x] Add deterministic regression tests.
- [ ] Run branch CI and review test results.
- [ ] Validate against a consented/de-identified gold CV corpus before setting accuracy targets.
