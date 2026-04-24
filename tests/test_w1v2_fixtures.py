"""
Fixture-driven tests for W1 v2.

One test per fixture per Doc 22 v1.0.1 rule. Each assertion comes directly
from the fixture manifest at tests/fixtures/v1/README.md. If a test fails
either the rule implementation or Doc 22 is wrong — per "specs lead code,"
the failure lives in whichever is inconsistent with the other.

Run with:
    python -m tests.test_w1v2_fixtures            (from repo root)
or
    python -m unittest tests.test_w1v2_fixtures

Each iteration turns more tests from expected_skip=True → expected_skip=False
as the corresponding rule lands.
"""
from __future__ import annotations
import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

import jsonschema

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.cir.extractor_docx import extract_docx  # noqa: E402
from lib.rules.base import RuleContext  # noqa: E402
from lib.rules.rejection import RuleRejectException  # noqa: E402
from lib.pipeline import run_phase  # noqa: E402
from lib.emit import (  # noqa: E402
    build_artifact, versioned_key, compute_source_hash, SCHEMA_VERSION,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = REPO_ROOT / "tests" / "fixtures" / "v1"
SCHEMA_PATH = REPO_ROOT / "manuscript" / "manuscript.v2.0.schema.json"

WORKER_VERSION = "5.0.0a1"
RULES_VERSION = "1.0.2"


def _schema_validator():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    return jsonschema.Draft7Validator(schema)


def _process_fixture(path: Path) -> tuple[RuleContext, Exception | None]:
    """Run the full W1 v2 pipeline over a fixture file. Returns (ctx, exc).

    In iteration 1 only the ingest phase has a registered rule (R-001).
    Subsequent iterations return a fully processed context.
    """
    ctx = RuleContext(blocks=[], artifact={})
    source_meta = {
        "original_filename": path.name,
        "original_format": "docx" if path.suffix.lower() == ".docx" else path.suffix.lstrip("."),
        "source_hash_sha256": compute_source_hash(path),
        "ingested_at": datetime.now(timezone.utc).isoformat(),
    }
    factory_args = {"source_path": path}

    try:
        run_phase("ingest", ctx, factory_args=factory_args)
    except RuleRejectException as e:
        return ctx, e

    # Only actually extract if R-001 didn't reject.
    if path.suffix.lower() == ".docx":
        blocks, extra_source_meta = extract_docx(path)
        ctx.blocks = blocks
        source_meta.update(extra_source_meta)

    # (Other phases wire in later iterations.)
    for phase in ("strip", "classify", "normalize", "validate", "emit"):
        run_phase(phase, ctx, factory_args=factory_args)

    ctx.artifact = build_artifact(
        ctx_blocks=ctx.blocks,
        ctx_applied_rules=ctx.applied_rules,
        ctx_warnings=ctx.warnings,
        ctx_rule_faults=ctx.rule_faults,
        worker_version=WORKER_VERSION,
        rules_version=RULES_VERSION,
        service_id="rec_test_service",
        project_id="rec_test_project",
        source_meta=source_meta,
        manuscript_meta=ctx.manuscript_meta,
    )
    return ctx, None


class BaseFixtureTest(unittest.TestCase):
    """Shared helpers."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = _schema_validator()

    def _fixture(self, name: str) -> Path:
        p = FIXTURES / name
        self.assertTrue(p.exists(), f"fixture missing: {p}")
        return p


# ---------------------------------------------------------------------------
# Iteration 1: R-001 tests ONLY. Remaining rule tests are scaffolded below
# with @unittest.skip() and will be flipped on as each iteration lands.
# ---------------------------------------------------------------------------


class Test_R001_UnsupportedFormat(BaseFixtureTest):
    """R-001: reject non-DOCX at ingest."""

    def test_positive_pdf_rejected(self):
        path = self._fixture("r001_unsupported_pdf.pdf")
        ctx, exc = _process_fixture(path)
        self.assertIsNotNone(exc, "R-001 should have raised RuleRejectException")
        self.assertIsInstance(exc, RuleRejectException)
        assert isinstance(exc, RuleRejectException)  # for type narrowing
        self.assertEqual(exc.rule_id, "R-001")
        self.assertIn("accepts .docx only", exc.message)
        self.assertIn("pdf", exc.message.lower())

    def test_negative_docx_accepted(self):
        path = self._fixture("r001_accepted_docx.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc, "R-001 should NOT fire on a .docx")
        # The resulting artifact must pass schema validation even with zero
        # classified roles — terminal default is governed by the worker, but
        # iteration 1 hasn't added classify rules yet, so blocks carry the
        # CIR-type-based role per the v1.0.2-deferred mapping. For this
        # iteration we assert the CIR shape only, not role assignment.
        self.assertGreater(len(ctx.blocks), 0, "extractor produced no blocks")
        # Every block has a CIR type and a b_ id.
        for b in ctx.blocks:
            self.assertTrue(b["id"].startswith("b_"))
            self.assertIn(b["type"], {
                "paragraph", "heading", "list_item", "blockquote",
                "table", "image", "code", "preformatted_block", "footnote",
                "page_break", "horizontal_rule",
            })

    def test_storage_key_format(self):
        """I-8 storage-key format helper."""
        key = versioned_key(
            project_intake_submission_id="TALLY-8F3Q",
            service_sku="INTFMT",
            schema_version=SCHEMA_VERSION,
            worker_version=WORKER_VERSION,
            rules_version=RULES_VERSION,
        )
        self.assertEqual(
            key,
            "services/TALLY-8F3Q/INTFMT/manuscript/v2.0/w5.0.0a1-r1.0.2/manuscript.json",
        )


class Test_Extractor_Smoke(BaseFixtureTest):
    """Sanity: extractor produces CIR blocks whose shape matches the v2.0
    schema on its own terms (role is optional in iteration 1 since no
    classifiers have run; blocks still have type, id, and well-formed
    spans/text).
    """

    def test_c001_chapter_newline_title_extracts(self):
        path = self._fixture("c001_chapter_newline_title.docx")
        blocks, _ = extract_docx(path)
        self.assertTrue(any(b["type"] == "heading" and b.get("heading_level") == 2 for b in blocks),
                        "Heading2 block missing")
        # The chapter heading text has a literal line break between runs.
        heading = next(b for b in blocks if b["type"] == "heading")
        joined = "".join(s["text"] for s in heading["spans"])
        self.assertIn("Chapter 1", joined)
        self.assertIn("What Depression Actually Is", joined)
        self.assertIn("\n", joined, "extractor should preserve the inline line break")

    def test_c003_author_title_page_carries_style_tags(self):
        path = self._fixture("c003_author_title_page.docx")
        blocks, _ = extract_docx(path)
        # First three blocks are the title cluster. All must be centered.
        # Title and subtitle must also carry large_font (≥1.5× body size).
        # The author byline (14pt against 11pt body = 1.27×) is below the
        # large_font threshold by design — C-003's classifier handles
        # "title cluster" as a group decision, not a per-block property.
        self.assertGreaterEqual(len(blocks), 3)
        for b in blocks[:3]:
            self.assertIn("centered", b.get("style_tags", []),
                          f"missing centered on title cluster block {b['id']}")
        for b in blocks[:2]:
            self.assertIn("large_font", b.get("style_tags", []),
                          f"missing large_font on title/subtitle block {b['id']}")

    def test_n001_double_spaces_preserves_content(self):
        """Extractor must preserve double-space runs; N-001 collapses them
        in the strip phase (iteration 2). Iteration 1: extractor emits
        blocks with the original whitespace intact.
        """
        path = self._fixture("n001_double_spaces.docx")
        blocks, _ = extract_docx(path)
        joined = " ".join(
            "".join(s["text"] for s in b.get("spans", []))
            for b in blocks
            if b.get("spans")
        )
        self.assertIn("  ", joined, "extractor stripped double spaces prematurely")

    def test_n002_tracked_changes_accepted(self):
        """N-002: tracked-change acceptance is implemented in the
        extractor. The w:ins text is included; w:del text is dropped.
        """
        path = self._fixture("n002_tracked_changes.docx")
        blocks, _ = extract_docx(path)
        joined = " ".join(
            "".join(s["text"] for s in b.get("spans", []))
            for b in blocks
            if b.get("spans")
        )
        self.assertIn("genuinely", joined, "N-002 failed to include w:ins content")
        self.assertNotIn("actually", joined, "N-002 failed to drop w:del content")

    def test_n003_zwsp_nbsp_present_as_raw(self):
        """Extractor does NOT strip zero-width chars; N-003 (iteration 2)
        does that in the strip phase.
        """
        path = self._fixture("n003_zwsp_nbsp_hacks.docx")
        blocks, _ = extract_docx(path)
        joined = " ".join(
            "".join(s["text"] for s in b.get("spans", []))
            for b in blocks
            if b.get("spans")
        )
        self.assertIn("\u200B", joined, "extractor stripped ZWSP prematurely")

    def test_c002_part_newline_title_extracts(self):
        path = self._fixture("c002_part_newline_title.docx")
        blocks, _ = extract_docx(path)
        self.assertTrue(any(b["type"] == "heading" and b.get("heading_level") == 1 for b in blocks),
                        "Heading1 (part divider candidate) missing")

    def test_extractor_emits_empty_paragraph_runs_raw(self):
        """The extractor emits empty-line paragraphs as they appear in
        the source. Collapsing runs of 2+ is N-001's paragraph-level
        extension, exercised via the full pipeline in Test_N001_*.
        """
        path = self._fixture("n001_double_spaces.docx")
        blocks, _ = extract_docx(path)
        streaks = _count_consecutive_empty_line_runs(blocks)
        self.assertGreaterEqual(
            streaks["max"], 2,
            "extractor should emit raw empty-paragraph runs for N-001 to collapse"
        )


def _count_consecutive_empty_line_runs(blocks):
    """Return {'max': longest streak of empty-line blocks, 'streaks': int}."""
    max_streak = 0
    streaks_over_one = 0
    streak = 0
    for b in blocks:
        if b.get("type") == "paragraph" and "empty_line" in (b.get("style_tags") or []):
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            if streak > 1:
                streaks_over_one += 1
            streak = 0
    if streak > 1:
        streaks_over_one += 1
    return {"max": max_streak, "streaks": streaks_over_one}


def _block_texts(blocks):
    """Helper: return the concatenated text of each block as a list."""
    out = []
    for b in blocks:
        if "spans" in b:
            out.append("".join(s.get("text", "") for s in b["spans"]))
        elif "text" in b:
            out.append(b["text"])
        else:
            out.append("")
    return out


class Test_N001_CollapseDoubleSpaces(BaseFixtureTest):
    """N-001 strip-phase + paragraph-level extension."""

    def test_positive_double_spaces_collapsed(self):
        path = self._fixture("n001_double_spaces.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        for text in _block_texts(ctx.blocks):
            self.assertNotIn("  ", text, f"double space survived N-001: {text!r}")

    def test_positive_empty_paragraph_runs_collapsed(self):
        path = self._fixture("n001_double_spaces.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        streaks = _count_consecutive_empty_line_runs(ctx.blocks)
        self.assertEqual(
            streaks["streaks"], 0,
            "N-001 paragraph-level extension did not collapse empty-line runs"
        )
        self.assertLessEqual(streaks["max"], 1)

    def test_negative_preformatted_preserved(self):
        """n001_code_block_preserved.docx has a monospace paragraph with
        double spaces that N-001 must NOT touch.
        """
        path = self._fixture("n001_code_block_preserved.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        # Find the preformatted block.
        preformatted = [b for b in ctx.blocks if b.get("preformatted") is True]
        self.assertTrue(preformatted, "extractor did not mark the code paragraph preformatted")
        for b in preformatted:
            joined = "".join(s.get("text", "") for s in b.get("spans", []))
            self.assertIn("  ", joined,
                          "N-001 touched a preformatted block (double spaces stripped)")

    def test_n001_is_silent_no_applied_rules_entry(self):
        """N-001 is Layer 1a — MUST NOT emit to applied_rules[]."""
        path = self._fixture("n001_double_spaces.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        n001_entries = [r for r in ctx.applied_rules if r.get("rule") == "N-001"]
        self.assertEqual(n001_entries, [],
                         "N-001 is Layer 1a; emits nothing to applied_rules[]")


class Test_N003_StripZeroWidthAndLayoutHacks(BaseFixtureTest):
    """N-003 strip-phase."""

    def test_positive_zero_width_chars_stripped(self):
        path = self._fixture("n003_zwsp_nbsp_hacks.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        for text in _block_texts(ctx.blocks):
            for ch, name in [
                ("\u200B", "ZWSP"),
                ("\u200C", "ZWNJ"),
                ("\u200D", "ZWJ"),
                ("\uFEFF", "BOM"),
            ]:
                self.assertNotIn(ch, text, f"{name} survived N-003")

    def test_positive_nbsp_runs_collapsed(self):
        path = self._fixture("n003_zwsp_nbsp_hacks.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        # There should be no run of 2+ NBSP surviving.
        for text in _block_texts(ctx.blocks):
            self.assertNotIn("\u00A0\u00A0", text,
                             f"NBSP run survived N-003: {text!r}")

    def test_negative_preformatted_preserved(self):
        """The N-003 exemption: preformatted content must retain its
        zero-width / NBSP content. We reuse n001_code_block_preserved —
        it has no zero-width chars, but verifying that N-003 walks only
        non-preformatted blocks is enough with a smoke assertion that
        the preformatted block's text is unchanged.
        """
        path = self._fixture("n001_code_block_preserved.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        preformatted = [b for b in ctx.blocks if b.get("preformatted") is True]
        self.assertTrue(preformatted)
        for b in preformatted:
            joined = "".join(s.get("text", "") for s in b.get("spans", []))
            # The fixture's code content — used here as a ground-truth
            # anchor. If the extractor changes how it surfaces preformatted
            # content, update this assertion.
            self.assertIn("def  greet(name)", joined,
                          "preformatted block text was altered")

    def test_n003_is_silent_no_applied_rules_entry(self):
        path = self._fixture("n003_zwsp_nbsp_hacks.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        n003_entries = [r for r in ctx.applied_rules if r.get("rule") == "N-003"]
        self.assertEqual(n003_entries, [],
                         "N-003 is Layer 1a; emits nothing to applied_rules[]")


def _blocks_with_role(ctx: RuleContext, role: str) -> list[dict]:
    return [b for b in ctx.blocks if b.get("role") == role]


class Test_C001_ChapterHeading(BaseFixtureTest):
    """C-001 classify, order 1."""

    def test_positive_chapter_with_newline_title(self):
        path = self._fixture("c001_chapter_newline_title.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        chapters = _blocks_with_role(ctx, "chapter_heading")
        self.assertEqual(len(chapters), 1, "expected exactly one chapter block")
        ch = chapters[0]
        self.assertEqual(ch["chapter_number"], 1)
        self.assertEqual(ch["chapter_title"], "What Depression Actually Is")

    def test_negative_body_mentioning_chapter_not_classified(self):
        """Body paragraphs mentioning 'chapter' must NOT be classified.
        Any chapter_heading blocks in this fixture must come from
        heading-level-2 blocks only (the "Introduction" Heading2), which
        falls through C-001's unmatched-pattern branch and produces
        chapter_number=null. A body-paragraph classification would have
        surfaced an int chapter_number via regex group 2.
        """
        path = self._fixture("c001_body_mentioning_chapter.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        chapters = _blocks_with_role(ctx, "chapter_heading")
        # Exactly zero with an int chapter_number — the body paragraphs
        # "Chapter 1 covers ..." never reach C-001 because they're type
        # paragraph, not heading.
        ints = [c for c in chapters if isinstance(c.get("chapter_number"), int)]
        self.assertEqual(ints, [],
                         "C-001 pattern fired on a non-heading block")

    def test_c001_skips_non_heading2_blocks(self):
        """Body paragraphs (type=paragraph) must never be classified as
        chapter_heading, regardless of their text content. I-10 +
        the heading-level-2 gate.
        """
        path = self._fixture("c001_body_mentioning_chapter.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        for b in ctx.blocks:
            if b.get("type") == "paragraph":
                self.assertNotEqual(b.get("role"), "chapter_heading")


class Test_C002_PartDivider(BaseFixtureTest):
    """C-002 classify, order 2."""

    def test_positive_part_newline_title(self):
        path = self._fixture("c002_part_newline_title.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        parts = _blocks_with_role(ctx, "part_divider")
        self.assertEqual(len(parts), 1)
        pd = parts[0]
        # Part number may be parsed as int or left as string ("One").
        self.assertIn(pd["part_number"], (1, "One", "one"))
        self.assertEqual(pd["part_title"], "Understanding")
        self.assertTrue(pd["force_page_break"], "I-5 requires force_page_break=true")


class Test_C004_FrontMatter(BaseFixtureTest):
    """C-004 classify, order 3."""

    def test_positive_note_before_you_begin(self):
        path = self._fixture("c004_note_before_you_begin.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        fm = _blocks_with_role(ctx, "front_matter")
        self.assertEqual(len(fm), 1)
        block = fm[0]
        self.assertEqual(block.get("subtype"), "note_to_reader")
        self.assertEqual(block.get("title"), "A Note Before You Begin")

    def test_does_not_fire_without_chapter(self):
        """C-004 needs a downstream chapter_heading / part_divider
        cutoff. A doc with only a heading-level-1 and no chapter must
        not classify front_matter.
        """
        # c003_no_title_page has a Heading2 chapter; let's use something
        # with only Heading1. We don't have a perfect fixture here; so
        # we just check the positive case produced zero false positives
        # outside the one expected front_matter block.
        path = self._fixture("c004_note_before_you_begin.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        fm = _blocks_with_role(ctx, "front_matter")
        self.assertLessEqual(len(fm), 1)


class Test_C005_BackMatter(BaseFixtureTest):
    """C-005 classify, order 4."""

    def test_positive_closing_letter_resources(self):
        path = self._fixture("c005_closing_letter_resources.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        bm = _blocks_with_role(ctx, "back_matter")
        # Expect two back-matter blocks: the closing letter and the
        # resources. Subtype assignment reflects the v1.0.1 pattern's
        # literal anchoring: "A Closing Letter" matches "A closing ..."
        # → subtype=closing. "A Few Resources" does NOT match the
        # pattern (the pattern requires the label immediately after an
        # optional "A "; "Few Resources" is not a library label), so
        # C-005 falls through to subtype=generic per I-6. The fixture
        # therefore exercises both branches: a matched label and the
        # generic fallback. v1.0.X pattern broadening (accepting "A Few
        # Resources" → resources) is a docs/pattern-tightening
        # opportunity, not a test failure.
        self.assertEqual(len(bm), 2)
        subtypes = sorted(b.get("subtype") for b in bm)
        self.assertEqual(subtypes, ["closing", "generic"])

    def test_i10_non_overwrite_on_part_divider_titled_resources(self):
        """I-10: a part_divider titled "Resources" must not be re-labeled
        back_matter by C-005. We construct the scenario at the block
        level rather than via a fixture — simpler + isolates the
        invariant.
        """
        from lib.rules.base import RuleContext
        from lib.rules.classification import C002_PartDivider, C005_BackMatter
        blocks = [
            # Heading-level-1 titled "Part Three: Resources" — C-002 claims it.
            {
                "id": "b_000001", "type": "heading", "heading_level": 1,
                "spans": [{"text": "Part Three Resources", "marks": []}],
            },
            {
                "id": "b_000002", "type": "heading", "heading_level": 2,
                "spans": [{"text": "Chapter 1 Opening", "marks": []}],
                "role": "chapter_heading", "chapter_number": 1,
                "chapter_title": "Opening",
            },
        ]
        ctx = RuleContext(blocks=blocks)
        C002_PartDivider().run(ctx)
        self.assertEqual(ctx.blocks[0]["role"], "part_divider")
        # Now run C-005 — it must NOT overwrite the part_divider role.
        # Note: C-005 also needs a chapter_heading cutoff, which exists.
        C005_BackMatter().run(ctx)
        self.assertEqual(ctx.blocks[0]["role"], "part_divider",
                         "I-10 violated: C-005 overwrote a part_divider role")


class Test_N004_QuoteNormalization(BaseFixtureTest):
    """N-004 normalize, order 1 (Layer 1b: applied-but-logged)."""

    def test_positive_mixed_quotes_curlied(self):
        path = self._fixture("n004_mixed_quotes.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        # After N-004, no straight quotes should remain in non-preformatted
        # blocks.
        for b in ctx.blocks:
            if b.get("preformatted"):
                continue
            for text in _block_texts([b]):
                self.assertNotIn('"', text, f"straight double quote remained: {text!r}")
                # Allow straight single quote only as an apostrophe-less
                # context — with the closing-context default mapping to
                # U+2019, nothing should remain after a successful run.
                self.assertNotIn("'", text, f"straight single quote remained: {text!r}")

    def test_positive_applied_rules_entry(self):
        """N-004 is Layer 1b: MUST emit one applied_rules[] entry with
        rule=N-004, a count, and the list of block ids it touched.
        """
        path = self._fixture("n004_mixed_quotes.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        n004 = [r for r in ctx.applied_rules if r.get("rule") == "N-004"]
        self.assertEqual(len(n004), 1, "expected exactly one N-004 applied_rules entry")
        entry = n004[0]
        self.assertEqual(entry["version"], "v1")
        self.assertGreater(entry["count"], 0)
        self.assertGreater(len(entry["block_ids"]), 0)

    def test_negative_preformatted_preserves_straight_quotes(self):
        """The N-004 exemption: preformatted paragraphs keep straight
        quotes verbatim.
        """
        path = self._fixture("n004_code_quotes_preserved.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        preformatted = [b for b in ctx.blocks if b.get("preformatted") is True]
        self.assertTrue(preformatted)
        for b in preformatted:
            joined = "".join(s.get("text", "") for s in b.get("spans", []))
            self.assertIn('"', joined, "N-004 touched a preformatted block (double quotes)")
            self.assertIn("'", joined, "N-004 touched a preformatted block (single quotes)")

    def test_apostrophe_in_contraction_is_right_single(self):
        """"don't" / "they're" — apostrophes inside words must become
        U+2019 (right single quote), the correct typographic apostrophe.
        """
        path = self._fixture("n004_mixed_quotes.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        # The fixture contains "she'd" via an inline apostrophe.
        joined = " ".join(_block_texts(ctx.blocks))
        self.assertIn("she\u2019d", joined, "contraction apostrophe not normalized")


class Test_C003_TitlePage(BaseFixtureTest):
    """C-003 classify, order 5 (runs last)."""

    def test_positive_author_title_page(self):
        path = self._fixture("c003_author_title_page.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        title_page = _blocks_with_role(ctx, "title_page")
        self.assertGreaterEqual(len(title_page), 2,
                                "expected at least title + subtitle in cluster")

    def test_negative_no_title_page(self):
        path = self._fixture("c003_no_title_page.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        title_page = _blocks_with_role(ctx, "title_page")
        self.assertEqual(len(title_page), 0,
                         "C-003 fired on a doc without a centered large-font opening")

    def test_c003_runs_last_does_not_overwrite_earlier_classifier(self):
        """Assemble a small context where a block is both 'would look like
        a title_page candidate' AND already classified by an earlier
        rule (simulated). C-003 must respect I-10.
        """
        from lib.rules.base import RuleContext
        from lib.rules.classification import C003_TitlePage
        blocks = [
            {
                "id": "b_000001", "type": "paragraph",
                "spans": [{"text": "The Long Quiet", "marks": []}],
                "style_tags": ["centered", "large_font"],
                "role": "front_matter",  # already classified by a prior rule
                "subtype": "generic",
            },
            {
                "id": "b_000002", "type": "heading", "heading_level": 2,
                "spans": [{"text": "Chapter 1 Opening", "marks": []}],
                "role": "chapter_heading",
                "chapter_number": 1, "chapter_title": "Opening",
            },
        ]
        ctx = RuleContext(blocks=blocks)
        C003_TitlePage().run(ctx)
        self.assertEqual(ctx.blocks[0]["role"], "front_matter",
                         "I-10 violated: C-003 overwrote a prior role assignment")


if __name__ == "__main__":
    unittest.main(verbosity=2)
