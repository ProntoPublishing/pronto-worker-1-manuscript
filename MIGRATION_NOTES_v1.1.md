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
- Iter 3+: stratum detection (§2.2), part-word precedence (§2.3), C-001/C-002 rewire,
  C-003 redesign (§3), validators (§4), N-005, pStyle synthesis (pending flag ruling).

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
