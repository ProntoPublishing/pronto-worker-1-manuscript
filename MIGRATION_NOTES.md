# W1 v5.0.0 migration notes

**Branch:** `feature/w1-v2-impl`
**Status:** Deployment-ready cut. **DO NOT MERGE. DO NOT DEPLOY.**
**Date:** 2026-04-24

This file documents the state of Worker 1 on the `feature/w1-v2-impl`
branch after iteration 7 of the v2 rewrite. The code here is the
manuscript.v2.0 producer that implements Doc 22 v1.0.2 as a phased
rule pipeline. It is complete enough to deploy — tests green, schema
valid, pipeline produces I-2-conformant artifacts on every fixture —
but a deploy is explicitly gated behind several preconditions that
haven't landed yet. Merging this branch to `main` without resolving
the gates below will break production.

## What lives on this branch

### New modules

| Path | Role |
|---|---|
| `lib/cir/types.py` | CIR vocabularies (frozen) + block/span builders |
| `lib/cir/extractor_docx.py` | DOCX → CIR extractor (N-002 embedded) |
| `lib/rules/base.py` | `RuleContext` + `Rule` protocol |
| `lib/rules/registry.py` | Phase + order registry |
| `lib/rules/rejection.py` | R-001 |
| `lib/rules/normalization.py` | N-001, N-003, N-004 |
| `lib/rules/classification.py` | C-001, C-002, C-003, C-004, C-005 |
| `lib/rules/terminal_default.py` | Doc 22 v1.0.2 CIR-type → role mapping |
| `lib/rules/validation.py` | V-001, V-002, V-003, V-004 |
| `lib/rules/human.py` | H-001 |
| `lib/pipeline.py` | Phase orchestrator + fault-safe emission |
| `lib/emit.py` | Artifact builder + I-8 versioned-key helper |
| `manuscript/manuscript.v2.0.schema.json` | JSON Schema for v2.0 artifacts |
| `tests/test_w1v2_fixtures.py` | 51 tests, all green |
| `tests/fixtures/v1/` | 23 DOCX + 1 PDF fixtures + manifest |

### Rewritten

- `pronto_worker_1.py` — v5.0.0-a1 pipeline orchestrator. Replaces the
  v4.x extract→detect→build→validate→upload flow with the v2 pipeline.
  Old behavior can be recovered from `main`.
- `app.py` — health-check now reports `version` from `WORKER_VERSION`
  and `rules_version` from `RULES_VERSION`. The `/process` endpoint is
  signature-compatible with the v4.x path (same JSON body, same
  response shape for the success/error paths).

### Untouched (kept for backward-compat reading)

- `lib/block_extractor.py`, `lib/warning_detector.py`,
  `lib/artifact_builder.py`, `lib/artifact_validator.py`,
  `lib/artifact_validate.py`, `lib/artifact_registry.py`,
  `lib/output_validator.py`, `lib/manuscript_schema.py`,
  `manuscript/manuscript.v1.0.schema.json`.
- These are v1.x producer/validator modules no longer used by the v5.0
  orchestrator. They remain in tree as reference until the shared-
  library consolidation lands (tracked separately).

## No-deploy gates

Three gates must all be green before this branch merges to `main` and
ships to Railway. Each is the responsibility of a separate workstream.

### Gate 1 — W2 v1.3 parallel-reader

Worker 2 today reads `manuscript.v1.0` artifacts. A v5.0 deployment
would start producing `manuscript.v2.0` artifacts at the new versioned
key, which W2 can't parse. W2 must ship a v1.3 release that
parallel-reads both schemas (detect `schema_version` on ingest,
dispatch). See the `feature/consume-manuscript-v2` branch plan noted
in the prior contract package's MIGRATION_NOTES. W1 v5.0 merges after
W2 v1.3 is on main and deployed.

### Gate 2 — Corpus testing conversation

Doc 22 v1.0.x rules are tuned against The Long Quiet plus the 23
synthetic fixtures in `tests/fixtures/v1/`. Before production, a small
corpus of real manuscripts (10–12 books per the Operational Policy
observability note) needs to run through this pipeline so rule
behavior gets validated against input the synthetic fixtures don't
cover. The corpus conversation is queued as the next
post-iter-7 step.

Items flagged during the rewrite that the corpus conversation should
also settle:

- **C-005 pattern broadening** for "A Few X" / "Some X" headings.
  Currently falls through to `subtype: "generic"` — correct per v1.0.1
  pattern anchoring, but the fallback may be too frequent on real books.
- **Byline "by " prefix** in C-003 title-page extraction. Currently
  emits `author: "by Test Author"` — literal extraction. Single-strip-
  point in C-003 is cleaner than downstream consumers each stripping
  independently.
- **V-002 near-inertness** — V-002 fires only when chapter_heading
  blocks have differing (type, heading_level) signatures. With the
  current C-001 (heading-level-2 only), all chapters share the same
  signature, so V-002 rarely fires. Will become useful when the
  classifier broadens. No action; flag only.
- **Fault-threshold defaults** (`max_layer_2_faults_before_fail=3`,
  `any_layer_4_fault_fails=true`) per Doc 22 §Operational Policy.
  Current defaults are untested against real fault densities.

### Gate 3 — Storage-key placeholders ✅ CLOSED 2026-04-25

`pronto_worker_1.py._derive_storage_ids()` now reads the canonical
Airtable lookup fields directly off the Service record:

- **`intake_submission_id`** ← `Project Intake Submission ID`
  (multipleLookupValues lookup of `Intake Submission ID` on the linked
  Project record; canonical source field is on Projects).
- **`service_sku`** ← `Service SKU` (multipleLookupValues lookup of
  `SKU` on the linked Service Type record from the Service Catalog;
  canonical source field is on Service Catalog).

No fallbacks. If either lookup is empty the run raises a clear
`ValueError` and flips the Service to Failed via the existing
fault-safe path — the data-integrity problem surfaces in Airtable
where it can be corrected, instead of being papered over with a
synthesized key. This preserves I-8 strictly: every storage key
matches the artifact body's identifiers, and every artifact's
identifiers trace to the Airtable source of truth.

A `_first_lookup_value()` helper in `pronto_worker_1.py` reads the
multipleLookupValues format defensively (handles list[str], bare
string, and empty-list cases). Six unit tests cover the contract:
both lookups present, defensive string-mode, missing-intake raise,
missing-sku raise, empty-list-treated-as-missing, and URL-safe
sanitization of spaces/slashes in the resulting key segments.

## What's pending on the v1.1 consolidation punchlist (logged, no action)

- Doc 22 v1.1 merge of patches v1.0.1 + v1.0.2.
- Byline prefix stripping in C-003 (single-strip-point concern).
- C-005 pattern broadening.
- V-002 near-inertness observation.
- Shared-library refactor for `manuscript_schema.py` across W1/W2.
- REVIEW_NOTES M9 (two parallel validators) — resolved in v5.0 by
  retiring the JSON-schema-only path inside the worker; full
  consolidation lands with the shared library.

## How to verify the branch locally

From the repo root:

```bash
pip install -r requirements.txt
python -m unittest tests.test_w1v2_fixtures
# expect: Ran 51 tests in ~1s, OK
```

End-to-end dry run (no Airtable / R2 touched):

```python
from tests.test_w1v2_fixtures import _process_fixture, FIXTURES
ctx, _ = _process_fixture(FIXTURES / "v001_chapters_continuous.docx")
print(ctx.artifact)  # manuscript.v2.0 artifact as a dict
```

## When any gate clears

1. Rebase the branch onto `main` if it has drifted.
2. Re-run the full test suite.
3. Close out the corresponding gate in this document.
4. Do NOT merge until ALL three gates are green.

When all three are green, the merge sequence is:

1. Merge `feature/consume-manuscript-v2` on `pronto-worker-2-interior`
   first and deploy W2 v1.3. Verify parallel-reader against a v1.0
   and a v2.0 artifact.
2. Merge `feature/w1-v2-impl` here.
3. Railway redeploys W1 as v5.0.0 (drop the `-a1` pre-release suffix
   in `WORKER_VERSION` at merge time).
4. Watch the first 3–5 services process end-to-end. Verify
   `rule_faults_count == 0` in the majority case; investigate any
   that aren't.
