# fixtures/v1 — manifest

**23 fixtures (22 .docx + 1 .pdf), one per Doc 22 v1.0.1 rule where the rule entry names one.** Each fixture is small, focused on one scenario, and authored programmatically for reproducibility. The generator script is `build_fixtures_v1.py` in the scratch work directory (not checked into either worker repo).

Convention:
- **Positive fixture** — demonstrates the rule firing. Named `{ruleid}_{scenario}.docx`.
- **Negative fixture** — superficially looks similar but must NOT trigger the rule. Named with a distinguishing suffix.

All fixtures ride on Doc 22 v1.0.1 as the contract. Where the rule text has ambiguities that only resolve in v1.0.2 (the CIR-type → role mapping table), the fixture exercises the rule up to the rule's own specification and stops short of the mapping-table-dependent edges. Noted per-fixture below.

## Rule coverage

### Normalization (N)

#### N-001: Collapse double spaces (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `n001_double_spaces.docx` | + | Body paragraphs with deliberate double-space runs between words AND a sequence of 3 consecutive empty paragraphs. | `applied_rules[]` contains `{rule: "N-001", version: "v1"}`. Both the intra-paragraph double spaces AND the empty-paragraph run should collapse. No content change beyond whitespace. |
| `n001_code_block_preserved.docx` | − | A monospace-font paragraph containing `def  greet(name):` with intentional double spaces. The extractor should recognize this as preformatted (via font/style) and set `preformatted: true` on the block. | `applied_rules[]` does NOT reference this block for N-001. Double spaces preserved verbatim. |

**Note on the negative fixture:** It depends on the extractor recognizing monospace font as a preformatted signal. Doc 22 v1.0.1 says *"Set preformatted: true when the source indicates verbatim content (DOCX: fixed-width styled paragraphs, code styles; Markdown: fenced blocks)"*. The extractor contract MUST include "monospace font → preformatted: true" or this fixture can't pass. Flagging for the extractor spec.

#### N-002: Strip tracked changes (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `n002_tracked_changes.docx` | + | Document containing `<w:ins>genuinely </w:ins>` and `<w:del>actually </w:del>` in one paragraph. The ingest extractor should accept all tracked changes, resolving to `"The morning was genuinely quiet."` | Block content is the post-acceptance text. No surviving tracked-change markers. V-004 does NOT fire on the CIR. |

#### N-003: Strip zero-width and layout-hack characters (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `n003_zwsp_nbsp_hacks.docx` | + | A body paragraph embedding U+200B, U+200D, U+FEFF, and a run of 4 U+00A0 (non-breaking space). | After strip: zero-width chars removed; NBSP run collapsed to a single regular space. |

#### N-004: Quote normalization (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `n004_mixed_quotes.docx` | + | Body paragraphs mixing straight and curly single/double quotes. | `applied_rules[]` contains `{rule: "N-004", count: N, version: "v1"}`. All straight quotes normalized to directional. |
| `n004_code_quotes_preserved.docx` | − | Straight quotes inside a monospace-font (preformatted) paragraph. | N-004 MUST NOT fire on that block. Straight quotes preserved. |

### Classification (C)

#### C-001: Chapter heading detection (v1) — includes v1.0.1 Patch 3 regex fix

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `c001_chapter_newline_title.docx` | + | Heading2 whose runs are `"Chapter 1"` + line break + `"What Depression Actually Is"`. | Block emits `{role: "chapter_heading", chapter_number: 1, chapter_title: "What Depression Actually Is"}`. |
| `c001_body_mentioning_chapter.docx` | − | Body paragraphs (Normal style) that say `"As we will see in chapter 1, …"` and `"Chapter 1 covers foundations; chapter 2 covers application."` | Both blocks remain `role: "body_paragraph"`. C-001 only fires on heading-styled CIR blocks. |

**Not yet covered** (flagged for a follow-up fixture once the v1.0.1 Patch 3 regex lands): the "Chapter 5" (number-only) case, where the synthesized `chapter_title: "Chapter 5"` path should fire. Add `c001_chapter_number_only.docx` at the same time as Patch 3's implementation.

#### C-002: Part divider detection (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `c002_part_newline_title.docx` | + | Heading1 with `"Part One"` + line break + `"Understanding"`, followed by a Heading2 chapter. | Part block emits `{role: "part_divider", part_number: "One", part_title: "Understanding", force_page_break: true}` per I-5. |

#### C-003: Title page detection (v1) — runs last within Classify per v1.0 ordering

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `c003_author_title_page.docx` | + | Three opening paragraphs: centered, large-font, short — title, subtitle, author — followed by Heading2. | Cluster classified as `role: "title_page"` with extracted `{title, subtitle, author}`. |
| `c003_no_title_page.docx` | − | Two normal (non-centered, normal-size) body paragraphs followed by Heading2. | No title_page emitted. Both opening paragraphs remain `role: "body_paragraph"`. |

#### C-004: Front-matter classification (v1) — v1.0.1 Patch 5 disambiguation

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `c004_note_before_you_begin.docx` | + | Heading1 `"A Note Before You Begin"` appearing before the first Heading2 chapter. | Block emits `{role: "front_matter", subtype: "note_to_reader", title: "A Note Before You Begin"}` per C-004 pattern library + I-6. |

#### C-005: Back-matter classification (v1) — v1.0.1 Patch 5 disambiguation

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `c005_closing_letter_resources.docx` | + | Two Heading2 chapters, then Heading1 `"A Closing Letter"` and Heading1 `"A Few Resources"` AFTER the last chapter. | Both Heading1 blocks emit `role: "back_matter"` with subtypes `closing` and `resources` respectively. |

### Validation (V)

#### V-001: Chapter number continuity (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `v001_chapter_gap.docx` | + | Four Heading2 chapters numbered 1, 2, 4, 5. | `warnings[]` contains `{rule: "V-001", severity: "medium", detail: "chapter numbers [1, 2, 4, 5] — gap between 2 and 4", blocks: [...]}`. |
| `v001_chapters_continuous.docx` | − | Five Heading2 chapters numbered 1, 2, 3, 4, 5. | No V-001 warning. |

#### V-002: Heading style consistency (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `v002_inconsistent_chapter_styles.docx` | + | Six chapters. Four use Heading2 (dominant style). One uses centered-bold (Normal style with alignment+bold). One uses Heading2 again (not flagged). | `warnings[]` contains `{rule: "V-002", severity: "medium", detail: "4 chapters use Heading2; chapter_5 uses centered-bold", blocks: [...]}`. |

#### V-003: Space-loss heuristic (v1) — v1.0.1 Patch 3 narrow-to-heuristic-(a)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `v003_joined_words.docx` | + | Body text containing `"Theweather"` and `"thefirst"` (function-word-led joins that fail the dictionary check) and `"conditionwith"` (non-function-word-led — should NOT fire in v1.0.1 per heuristic-(a)-only scope). | `warnings[]` contains two V-003 entries — one per joined token that started with a function word. `conditionwith` is not flagged in v1.0.1 (see Doc 22 v1.0.1 V-003 note on deferred heuristics (b) and (c)). |
| `v003_legitimate_compounds.docx` | − | Body text containing `"Thereon"`, `"ourselves"`, `"birthday"`, `"thereafter"` — all function-word-prefixed OR function-word-led dictionary words. | Zero V-003 warnings. Dictionary check suppresses all. |

#### V-004: Tracked-changes residue detector (v1) — new in v1.0.1

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `v004_tracked_changes_leaked.docx` | + | Same source as `n002_tracked_changes.docx` — a DOCX with `<w:ins>` / `<w:del>`. Exercising V-004 requires simulating an extractor regression: feed this DOCX to an extractor that FAILS to strip the tracked-change markers, producing a CIR with surviving revision indicators. | With a buggy extractor: `warnings[]` contains a V-004 entry per block with surviving markers. With the correct extractor (N-002 applied): no V-004 warnings — which is what `v004_tracked_changes_resolved.docx` covers. |
| `v004_tracked_changes_resolved.docx` | − | Content as it appears AFTER N-002 has accepted the tracked changes — no revision markers in the source. | Zero V-004 warnings. |

**Note on V-004 testability:** V-004 inspects the CIR after the strip phase, not the DOCX. The positive fixture alone can't force V-004 to fire — the extractor must also misbehave. In practice the test harness will construct a CIR directly with a surviving marker and feed it to V-004. The DOCX exists to document the upstream scenario.

### Rejection (R)

#### R-001: Unsupported format rejection (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `r001_unsupported_pdf.pdf` | + | A 15-byte minimal PDF (`%PDF-1.4\n%%EOF\n`). Extension is `.pdf`. | R-001 halts at ingest; Service flips to `Failed` with Error Log: `"v1 Worker 1 accepts .docx only. Received: pdf."` |
| `r001_accepted_docx.docx` | − | A regular .docx. | R-001 does not fire. Processing continues. |

### Human-clarification (H)

#### H-001: Author-supplied title page vs intake metadata (v1)

| File | Kind | What it exercises | Expected output |
|---|---|---|---|
| `h001_author_title_and_intake.docx` | + | Same pattern as `c003_author_title_page.docx` — three centered, large-font opening paragraphs. C-003 fires, producing a `title_page` block. | At emit time, H-001 consults intake metadata (Airtable Service state). If intake also carries a title/author, H-001 emits `applied_rules[]` entry: `{rule: "H-001", decision: "used author title page; suppressed system-generated", version: "v1"}`. Optionally also emits a warning if author-extracted title differs from intake title. |

**Note on H-001 testability:** The DOCX alone is not sufficient. H-001 compares the extracted title_page against intake metadata that lives in Airtable, not in the DOCX. The test harness must pair this fixture with a mock intake record containing compatible (and, for the divergence branch, incompatible) title/author values.

## What's NOT in this directory yet

- **`c001_chapter_number_only.docx`** — tests the v1.0.1 Patch 3 number-only-chapter synthesis (`"Chapter 5"` → synthesized `chapter_title: "Chapter 5"`). Add this when Patch 3's implementation lands.
- **Fixtures for the five CIR types without Layer 2 role names** (`paragraph`, `code`, `preformatted_block`, `page_break`, `horizontal_rule`) — deliberately deferred until Doc 22 v1.0.2 (CIR-type → role mapping table) lands. Without the mapping, there's no single expected-`role` value to assert against, so the fixture expectation is under-specified.
- **Fixtures for rule faults** — would exercise I-7's fault-safe emission. Needs a rule-fault harness; out of scope for v1 seed.

## How the test harness will use this

The canonical test flow (out of scope for this directory; documented here as intent):

1. Load fixture DOCX via the v2 W1 extractor → CIR.
2. Run the rule pipeline (ingest → strip → classify → normalize → validate → emit) → v2.0 artifact.
3. Validate the artifact against `manuscript.v2.0.schema.json`.
4. Assert the expected-output table above for each rule ID.

A single failing assertion against a fixture means either (a) the rule implementation diverges from Doc 22, or (b) Doc 22 under-specifies and needs a v1.0.N patch. The doctrine is "specs lead code" — so (b) is a v1.0.N patch authored before the code changes, not a code-first fix.

## Regenerate

The fixtures are authored programmatically. The generator script
(`build_fixtures_v1.py`) lives outside the repos in the scratch work dir.
Running it is deterministic:

```bash
python build_fixtures_v1.py
```

Each fixture is idempotent in content but the .docx bytes will differ on
each regen because DOCX embeds timestamps. That's acceptable for fixture
behavior but may produce noise in diffs. Authoring tests against fixture
content rather than fixture bytes is the resolution.
