# Rules 1.2 — Gate 2 rulings Q1/Q3 (2026-07-16)

**Status: implemented per the Gate 2 rulings (Jesse + Manus + Claude);
this changelog stands in for a spec amendment doc (v2.3) — the changes
extend §2.2's machinery rather than amend its text. FOR MANUS REVIEW:
the four PROPOSED THRESHOLDS below and the two judgment calls.**

Worker 5.2.0-a1 / rules 1.2 / schema **unchanged at 2.1**.
Trigger: test 21 / corpus Book 16 — a Pandoc plain-text Frankenstein
with zero heading structure shipped as 162pp of continuous prose
(zero rule faults; V-005 fired and nothing consumed it — the delivery
gate for that shipped separately as W2 1.6.0).

## What's new

### C-007 — source-TOC detection (ruling Q3), classify order 1

Detects the SOURCE's own contents listing, early in the document:
- **shape (a)**: one block, ≥3 landmark-pattern entries, ≤20% residue
  alnum content outside the entries (the residue rule rejects prose
  that merely mentions chapters);
- **shape (b)**: a run of ≥3 consecutive PARAGRAPH blocks, each a bare
  landmark label (no trailing title — "Chapter one body." must not
  count; heading-typed label runs are real structure), ordinals
  non-decreasing per class.
An adjacent-above "Contents"/"Table of Contents" label joins either
shape. Runs FIRST so detected blocks are out of stratum analysis.

**Suppressed-not-deleted, no schema bump**: detected blocks become
`role: structural` + `subtype: source_toc` + a classification note.
The ruling offered "a source_toc role (or suppressed flag)"; both
would force schema 2.2 + a coordinated W2 reader/handler release.
Schema 2.1's role enum already carries `structural`, and W2 renders
non-page-break structural blocks as a traceability comment — identical
semantics, zero coordination. `subtype` is schema-legal on any block
(I-6's description names front/back matter; Doc 22 v1.2 drafting
should bless `source_toc`). **[JUDGMENT CALL 1 — Manus.]**

Parsed entries land at `ctx.extras["source_toc_entries"]` and are
used by C-008 as corroboration (noted on promoted blocks) — never a
prerequisite (Book 16 promotes with its shape-(a) block suppressed;
the synthetic no-TOC unit fixture promotes with none at all).

### C-008 — pattern-only landmark promotion (ruling Q1), classify order 3

Fires ONLY in zero-structure documents: no dominant landmark stratum
(C-001's analysis found no chapter-class match in any heading level or
visually gated paragraph) and no landmark roles assigned. The four
ruling requirements, as implemented:

1. **Per-class coherent sequence** — candidates grouped by section
   word ("letter" ≠ "chapter"); ordinals strictly increasing in
   document order; a restart is legal only where a part-class
   candidate sits between (promoted as the pivot part_divider).
2. **Whole-paragraph** — the block's entire normalized text is a
   single `match_landmark` instance, ≤ 80 chars
   (**PROPOSED THRESHOLD**: longest corpus landmark line is 21 chars;
   80 admits modest trailing titles, excludes prose sentences).
3. **Multiplicity** — ≥ 3 per class (**ruling text**).
4. **Dispersion** — consecutive candidates < 50 intervening words
   (**PROPOSED THRESHOLD**) form an adjacency cluster: clusters of ≥3
   get the source-TOC treatment (belt; C-007 normally catches them
   first), clusters of 2 are excluded from promotion but not marked.
   The shortest plausible real chapter dwarfs 50 words; TOC rows have
   ~0–5.

Promotion reuses C-001's assignment helpers (chapter_title synthesis,
ordinal-style notes, W2's label-shaped rendering path applies
unchanged). Every promoted block carries the marker note
`promoted via pattern-only path …`.

### V-006 — pattern-only promotion warning, validate order 6

Fires once (medium) when any landmark carries the C-008 marker:
"landmarks promoted by pattern-only path — no visual confirmation…".
**TRAINING WHEELS**: medium routes the finished book through W2
1.6.0's Review gate (same as V-005). Downgrade to "info" once a few
real books pass review clean — a one-line severity change here.

### Two coordination fixes shaken out by Book 16

- `analyze_strata` now skips role-carrying blocks (I-10 extension) —
  C-007's source-TOC blocks must not vote for strata. No-op for the
  1.1 corpus (nothing had roles at analysis time before C-007 existed).
- **C-004 head-H1 guard**: with pattern-only chapters giving C-004 a
  cutoff, its generic branch claimed Book 16's document-head H1
  ("Frankenstein") as front_matter before C-003 ran — killing
  manuscript_meta and H-001. An UNRECOGNIZED H1 that is the document's
  first content block is now left for C-003; recognized labels
  ("Preface", "A Note Before You Begin") classify exactly as before.
  (Reordering C-003 ahead of C-004 was tried first and rejected: it
  handed front-matter labels at the document head to the title-page
  cluster instead. **[JUDGMENT CALL 2 — Manus.]**)

### Registry order (classify): C-007(1) C-001(2) C-008(3) C-002(4) C-006(5) C-004(6) C-005(7) C-003(8)

Doc 22 v1.2 drafting must update the "Order within phase" fields and
confirm the provisional ids C-007/C-008/V-006.

## Acceptance (tests/acceptance_v12.py — 11/11 rows)

- **Book 16** (`corpus_sources/frankenstein_unstructured.docx` = test
  21's submission): 28 landmarks (Letter 1–4 + Chapter 1–24), 0 parts,
  V-005 SILENT, V-006 medium, source TOC (shape a + label) suppressed,
  manuscript_meta {Frankenstein / Mary Wollstonecraft Shelley}, schema
  2.1 valid, 0 faults. W2 render: **190pp** (vs 162pp structureless),
  28-row generated TOC with leaders, full 14-row Interior Standard
  harness PASS.
- **Book 17** (`…_unstructured_toc.docx` = Book 16 + fake shape-(b)
  contents block after the byline): fake TOC + label + originals all
  suppressed (31 structural blocks), landmark count still 28, zero
  fake landmarks before the first real opener.
- Full suite 165 tests; acceptance_v11 (the 1.1 §6 rows) stays 36/36 —
  the visual-gate path for styled documents is untouched.

## Parked (ruling Q2 → rules 1.3)

Epistolary lexicon growth. The lexicon IS data-driven-cheap: 1.3
touches `CHAPTER_CLASS_LEXICON` in `lib/rules/landmarks.py` (one
tuple; regexes derive from it) for {journal, diary, telegram, entry},
plus a date-shaped-heading rule for Dracula's "3 May. Bistritz." style
openers — that one is NEW shape work, not a lexicon line.
