# W1 v1.1 Classification Amendment — Migration Notes

**Branch:** `feature/w1-classification-v1.1` (off main @ `5ad242a`, deployed W1 v5.0.0-a1 / rules 1.0.2)
**Contract:** `W1_Structural-Classification_Amendment_SPEC_v2.2_FROZEN_2026-07-15.md` (Drive, Master Docs)
**Acceptance:** spec §6 — the six corpus artifacts re-run locally; every diff attributable.

---

## Drift attribution: the rules 1.0.2 → 1.0.3 delta (spec §6 requirement)

Deployed W1 runs rules **1.0.2**. Canon Doc 22 is **1.0.3** (2026-04-25, never deployed).
v1.1 ships both jumps at once, so acceptance diffs have TWO sources. The complete
1.0.2 → 1.0.3 delta (from pandoc-diff of the two canon DOCX files, 84 inserted lines,
nothing removed):

1. **Extractor pStyle → style_tags synthesis table (frozen for v1.0.3):**
   `Title → [centered, large_font]`, `Subtitle → [centered, large_font]`,
   `BookTitle → [centered, large_font]`, `Author → [centered]` — synthesized even when
   the paragraph carries no explicit alignment/size attributes; dedupe-merged with
   attribute-derived tags. Rationale: Pandoc and Word default styles emit no explicit
   centering, so C-003 sees no tags.
   ⚠️ **Flagged to spec owner:** SPEC v2.2 states "the extractor is untouched," but Doc 22
   v1.0.3 (which v1.1 ships) mandates this extractor change. Not blocking iterations 1–2
   (pure library code); needs a ruling before the extractor-adjacent iteration lands.
   Interaction: P&P's "meta extracted" acceptance row may be satisfied by §3's
   position/shape scoring alone, by this synthesis, or both — attribution matters.

2. **N-005 (new Layer 1a strip rule, order 3): strip external-source license boilerplate.**
   Six frozen Gutenberg patterns; heading-anchored forward walk with a negation guard;
   single summary `applied_rules[]` entry `{rule: N-005, version: v1, count: N}`.
   Fixtures named in canon: `n005_gutenberg_pride_and_prejudice.docx` (positive),
   `n005_author_supplied_text_with_word_gutenberg.docx` (negative).
   Interaction: N-005 changes junk-chapter counts in every Gutenberg corpus book —
   acceptance rows must attribute "junk chapter disappeared" to N-005, not to the
   classifier rework.

Nothing else changed between 1.0.2 and 1.0.3.

---

## Iteration plan (spec §2)

- **Iter 1 (THIS BRANCH, DONE): `lib/rules/ordinals.py`** — shared ordinal parser: arabic,
  roman (hoisted from W2 `848a259` `_chapter_number_as_int` — W2's copy should converge on
  this module when the shared-library item lands; flagged in the punchlist shared-lib entry),
  spelled words. Pure functions, exhaustive tests (incl. LXXIV, XXVII).
- **Iter 2 (THIS BRANCH, DONE): `lib/rules/landmarks.py`** — lexicons as config constants,
  whitespace normalization (NBSP), the §2.1 pattern with trailing-title, §2.1b unnumbered
  branch. Pure, NOT wired into classification. Tests use the six run_records' real strings.
- **Iter 3 (DONE, 2026-07-15): Q1/Q2 rulings wired into `lib/rules/landmarks.py`**
  per the v2.2.1 addendum. `match_landmark()` gains the Q2 fused variant (all three
  ordinal systems, parse-gated, `fused=True` on the match for the classifier's
  normalization warning). `match_landmark_lines()` now returns a `LandmarkScan`
  implementing Q1's two-stage algorithm: whole-text primary; per-line fallback valid
  only with EXACTLY one matching line (`ambiguous=True` + count on 2+, ruled warning
  at classification time); non-matching lines returned as `caption_lines` for §2.3
  routing. Candidate gating stays the classifier's job.
  **Q1 interpretation note:** the addendum's rationale says `match_landmark_lines()`
  "wires in as coded", but its normative text adds the exactly-one-line rule and
  caption routing, which the iter-2 helper lacked. Normative text wins; the helper
  was extended (return type changed to LandmarkScan). Not treated as an ambiguity —
  the ruling's behavioral spec is unambiguous.
  **Pinned edge (test-documented):** a block whose text is two heading lines
  ("CHAPTER II.\nCHAPTER III.") matches at stage 1 with the second line as trailing
  title — stage-1 primacy per the ruling; the exactly-one-line rule only governs
  stage 2. Not a corpus shape.
- **Iter 4 (DONE, 2026-07-15): stratum detection + C-001/C-002 v2 + schema v2.1.**
  `lib/rules/strata.py`: strata = heading levels + the visually gated short-paragraph
  stratum (short + centered + bold/large_font; SHORT_TEXT_MAX=120 config constant —
  spec gives the gate shape, not the number). Dominant stratum = max chapter-class
  match count, ties by earliest first match. **Documented simplification:** spec §2.2
  says "most members forming a coherent numbered sequence"; on all six books plain
  count picks the same stratum — revisit if a tie/incoherent cluster appears.
  `C001_LandmarkClassification` (v2): Q1 two-stage scan per candidate; part-class →
  part_divider in ANY stratum (§2.3 precedence); chapter-class only in dominant
  stratum (catch-all dead); §2.1b unnumbered (dominant stratum or visual gates);
  Q2 fused → "probable missing space" warning; Q1 ambiguous → warning + unclassified.
  Merged captions: heading keeps its full text (faithful carry — W2 1.3.1 already
  renders the caption line); caption count recorded in classification_notes.
  `C002_StructuralPartDetection` (v2): repeated-book-title shape above the dominant
  stratum (Frankenstein's 3 volume pages) → part_divider, part_number null.
  **Schema v2.1 pulled forward from iter 8** (v2.0 has additionalProperties:false —
  landmark_subtype needs the bump now): `manuscript/manuscript.v2.1.schema.json`
  (role enum + chapter_subtitle, landmark_subtype field, schema_version enum "2.1"),
  emit.py SCHEMA_VERSION="2.1", fixture harness validates against 2.1. Matches the
  W2 prereq branch (`feature/w2-schema-2.1-prereq`, accepts "2.1").
  Note: v1.0.2 fixture suite passed unchanged except the storage-key version segment
  and an import — the amendment preserves the catch-all's true positives by design.
- **Iter 5 (DONE, 2026-07-15): C-006 chapter_subtitle + C-003 v2.**
  `C006_ChapterSubtitle` (classify order 3): adjacent-below a landmark (empty_line
  blocks skipped) + short + style gate (italic / centered / subordinate heading
  level); scene-break ornaments excluded (must carry a letter/digit). **Rule id
  C-006 is provisional** — the spec names no Doc 22 id for the §2.3 promotion;
  confirm when Doc 22 v1.1 is drafted.
  `C003_TitlePage` v2 (§3): window = document start → first sustained body run
  (2+ consecutive ≥200-char paragraphs), cap 40 blocks, landmark-independent but
  never crossing a classified landmark; accepts paragraphs AND headings; candidate
  = short + alnum; **qualification = 2+ independent signals** from {tag:centered,
  tag:large_font, level:h1/h2, position:early} — the "no single precondition
  load-bearing" reading; threshold is the implementation choice, recorded here.
  Byline adjacency exception carried from v1 ("By X" / short name line).
  **Q3 mechanism attribution:** every member notes "qualified via: <signals>";
  summary at ctx.extras["c003_mechanism"] = "tag path" | "position/shape path".
  Classify order now: C-001, C-002, C-006, C-004, C-005, C-003.
- **Iter 6 (DONE, 2026-07-15): §4 validators.** V-001 v2: part-scoped continuity
  with the implicit first part (DQ Amendment 2), unnumbered landmarks excluded;
  warning detail names the scope. V-005 (NEW, provisional id — next free validator
  slot, confirm at Doc 22 v1.1 drafting): zero structural roles AND blocks>50 AND
  words>5,000 → medium warning. V-003 v2: observational — findings to module logger
  + ctx.extras["v003_observations"], never ctx.warnings, so they're out of the
  artifact and the Airtable Warning Count (= len(warnings)) automatically. **Demotion
  side-decision:** a missing wordfreq backend is now a log line + extras note, NOT a
  rule_fault (an observational rule shouldn't pollute Rule Fault Count); flagging
  here since Doc 22 v1.0.1 specified the fault.
- **Iter 7 (DONE, 2026-07-15): Doc 22 v1.0.3 deltas shipped (ruling Q3) + version
  bumps.** N-005 (`lib/rules/normalization.py`, strip order 3): the six frozen
  canon patterns verbatim from `22-manuscript-normalization-rules-v1.0.3.md.docx`,
  heading-anchored forward walk with the negation guard, single summary
  applied_rules entry. pStyle→style_tags synthesis in `lib/cir/extractor_docx.py`:
  frozen table (Title/Subtitle/BookTitle → centered+large_font; Author → centered),
  case-insensitive name lookup, dedupe-merged with attribute-derived tags.
  Versions: WORKER_VERSION 5.0.0-a1 → **5.1.0-a1**, RULES_VERSION 1.0.2 → **1.1**
  (worker, local driver, fixture harness, storage-key test).
- **Iter 8 (2026-07-15): §6 acceptance — 36/36 mechanical rows PASS**
  (`tests/acceptance_v11.py`, artifacts + report in `.acceptance_out/`).

  **Re-baseline (post-N-005 junk counts + headline numbers):**
  | Book | Chapters | Parts | Subtitles | N-005 removed | Warnings | Faults |
  |---|---|---|---|---|---|---|
  | Hatch | 9/9 (1–9) | 0 | 9 | 0 (author-supplied) | 0 | 0 |
  | P&P | 61/61 (1–61) | 0 | 0 | 24 | 2 (C-001 fused, ruled) | 0 |
  | Frankenstein | 27/27 | 3 (numbered from VOL markers) | 0 | 21 | 0 | 0 |
  | DQ | 126/126 | 1 (Volume II) | 0 | 22 | 0 | 0 |
  | Leaves | 0 | 34 | 0 | 18 | 0 | 0 |
  | Carol | 5/5 (1–5) | 0 | 5 | 27 | 0 | 0 |

  All junk chapters across the corpus are attributable to N-005 (boilerplate
  stripped pre-classification) + the dead catch-all (remaining junk H2s →
  generic `heading`). **P&P meta mechanism (Q3 row): TAG PATH** — pStyle
  synthesis supplied centered/large_font on the Pandoc Title/Author styles;
  every book's members carry "qualified via:" notes in classification_notes.

  **⚠️ Spec-premise mismatches found by acceptance (flagged, resolutions in code):**
  1. **Frankenstein repeats its title FIVE times, not three** (3 volume pages
     each followed by an "IN THREE VOLUMES. / VOL. n." paragraph + 2 bare
     half-titles). C-002 v2 resolution: when any repeated-title candidate has
     an adjacent part-pattern block, only confirmed candidates classify
     (numbered from the marker); if none confirm, all repeats classify with
     null numbers (the spec's imagined shape). Yields exactly 3, numbered 1–3.
  2. **"Claude Cumberbatch" does not appear anywhere in the_hatch_list.docx**
     (title page = title / ornament / 3-line subtitle / city / MCMXX year).
     The §6 meta row's author can only come from INTAKE via H-001
     reconciliation (H-001 "unchanged" per §3). Acceptance runs Hatch with the
     Book-01 intake and checks the H-001 decision; manuscript-side author is
     correctly null. Also fixed: roman-year "MCMXX" no longer name-shapes into
     the author slot (ordinal-parse guard in C-003 positional logic).
  3. **Frankenstein Vol I runs LETTER I–IV then CHAPTER I–VII** — one part,
     two legitimate numbered sequences. V-001 sub-scopes by section-word
     family (part × word), re-derived from heading text via the matcher.
     Required for the "V-001 silent" row; spec §2.4 doesn't state it.

  **Schema v2.1 deltas beyond the spec-stated bump (both surfaced by
  acceptance, both pre-existing):** block `title` property admitted (C-004/
  C-005 have written it since v1.0.1; v2.0 schema simply omitted it) and
  warnings rule pattern widened to `^[VHC]-\d{3}$` (Q1/Q2 ruled warnings
  originate in classify).

  **W1↔W2 coordination (§2.4 "W2 coordination is in §6 acceptance"):** with
  integer chapter_number, W2's synthesized-title equality check missed every
  label-shaped title → doubled headings ("CHAPTER 1 / LETTER I"). W2 prereq
  branch gains `_title_is_label()` (lexicon + arabic/roman/word ordinal parse,
  mirroring W1 — shared-lib punchlist) → label-shaped titles render once via
  `\chapter*`, preserving word + ordinal style. And W1 threads caption lines
  INTO multi-line chapter_title (W2 renders headings from chapter_title only —
  captions left in block text would silently drop; P&P's 34 ride the W2 v1.3.1
  multi-line mechanism).

  **§6 render verification (local, W2 v1.4.0 = prereq branch + main merges):**
  - P&P: 399pp (vs 404 in prod test 20 — delta = N-005's 24 stripped
    boilerplate blocks + 4 junk chapters gone, attributable), labels roman
    CHAPTER I→LXI, 34-caption probes render, 0 doubling.
  - Frankenstein: LETTER I–IV render as LETTERS (word preserved), chapters
    roman per volume (I–VII / I–IX / I–VII), 0 doubling, 3 volume title pages
    as part dividers + 2 half-titles as faithful generic headings, H-001
    title page from extracted meta.
  - Hatch: CHAPTER ONE…NINE (spelled style preserved), italic subtitles
    render, 33pp.
  - Carol: staves render once (letter-spaced heading style), stave-name
    subtitles beneath, source's own contents page carried faithfully.
  - DQ: 1,180pp, 126 numbered chapter labels, per-volume restarts (max 74),
    Volume II part divider.
  - **TOC + running headers: W2's template has neither** (no
    \tableofcontents; prod P&P has none either) — pre-existing template gap,
    same bucket as the addendum's "Noted, not ruled" running-headers item →
    rides Doc 23 render-contract work. The §6 "TOC/headers … sane" wording is
    read as "numbering sane" for this gate; FLAGGED for the spec owner.
  - **W2 render_local caveat:** pdf_generator's PDF-existence success
    criterion reports stale success when a previous local.pdf exists in the
    outdir and the new pass fails (MiKTeX first-pass nag). Acceptance renders
    were re-done in clean outdirs. Worth a small W2 fix (delete target before
    compile) — punchlist.

---

## ⚠️ SPEC QUESTIONS (flagged, not improvised — code implements spec-as-written)

**Q1 — §2.1 anchor vs P&P's caption-merged headings (blocks the 61/61 acceptance row).**
§2.1 matches `^<section-word> <ordinal>…$` on the whitespace-NORMALIZED WHOLE block text.
That is exactly right for DQ ("CHAPTER I.\n<TITLE>" collapses → matches with trailing
title). But P&P's 34 caption-merged headings are "<caption text>\n\nCHAPTER II." — the
chapter word is at the END; normalized whole-text does NOT match `^chapter`. Under the
spec as written those 34 fail the pattern, and with the catch-all dead they are no longer
chapter_heading — contradicting §1's "228/228 matched" tally and §6's "P&P 61/61
preserved." The W2 render fix solved the analogous problem by line-splitting and taking
the line matching /^chapter/. The matcher needs a ruling: whole-text first, then per-line
fallback (recommended — preserves DQ trailing-title AND P&P caption-merge), or per-line
only, or whole-text only (P&P acceptance then needs rewriting). `match_landmark()`
implements whole-text per spec; a separate `match_landmark_lines()` helper exists so
iteration 3 can wire whichever the ruling picks without rework.

**Q2 — fused headings ("CHAPTERXXVII.", P&P has two).** §2.1 requires `\s+` between
section word and ordinal; fused forms fail. Also inside the "61/61 preserved" row.
Options: a no-space lexicon variant (matches the W2 fix's bare-prefix recognizer), or
accept 59/61 + a V-00x warning. Needs the same ruling pass as Q1.

---

## Tests

`tests/test_ordinals.py` + `tests/test_landmarks.py`. All strings in the landmark tests
are lifted verbatim from the six corpus run_records (positives AND negatives — Leaves'
poem titles, DQ's commendatory-verse titles must not match).
