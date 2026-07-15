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
- Iter 5+: chapter_subtitle role assignment (§2.3 below-stratum), C-003 redesign (§3),
  validators (§4), N-005, pStyle synthesis (ruled IN by Q3), rules_version bump.

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
