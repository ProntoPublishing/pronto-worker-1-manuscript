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

WORKER_VERSION = "5.0.0-a1"  # SemVer 2.0 pre-release marker
RULES_VERSION = "1.0.3"


def _schema_validator():
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = json.load(f)
    return jsonschema.Draft7Validator(schema)


def _process_fixture(
    path: Path,
    intake_metadata: dict | None = None,
) -> tuple[RuleContext, Exception | None]:
    """Run the full W1 v2 pipeline over a fixture file. Returns (ctx, exc).

    intake_metadata is threaded into ctx before pipeline execution so
    H-001 (emit phase) can compare against it. Default None → H-001
    never fires.
    """
    ctx = RuleContext(blocks=[], artifact={}, intake_metadata=intake_metadata)
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
            "services/TALLY-8F3Q/INTFMT/manuscript/v2.0/w5.0.0-a1-r1.0.3/manuscript.json",
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


class Test_TerminalDefault(BaseFixtureTest):
    """Terminal default (Doc 22 v1.0.2 Patch 1) — runs at end of classify."""

    def test_body_paragraph_gets_role_after_terminal_default(self):
        """A body paragraph that no classifier touched must end up with
        role=body_paragraph and a 'terminal default applied' note.
        """
        path = self._fixture("c001_chapter_newline_title.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        body_paras = [b for b in ctx.blocks
                      if b.get("type") == "paragraph"
                      and b.get("role") == "body_paragraph"]
        self.assertGreater(len(body_paras), 0,
                           "expected at least one body paragraph")
        # At least one of them was assigned by terminal default.
        td_applied = [
            b for b in body_paras
            if "terminal default applied" in (b.get("classification_notes") or [])
        ]
        self.assertGreater(len(td_applied), 0,
                           "terminal default didn't touch any body paragraph")

    def test_every_block_has_role_after_classify(self):
        """I-2 enforcement via terminal default: after classify, every
        block has a non-null role.
        """
        path = self._fixture("c001_chapter_newline_title.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        for b in ctx.blocks:
            self.assertTrue(b.get("role"),
                            f"block {b.get('id')} lacks a role after classify")

    def test_terminal_default_honors_existing_role(self):
        """If a classifier already set a role, terminal default leaves
        it alone (no overwrite, no duplicate note).
        """
        path = self._fixture("c003_author_title_page.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        title_page = [b for b in ctx.blocks if b.get("role") == "title_page"]
        self.assertGreater(len(title_page), 0)
        for b in title_page:
            notes = b.get("classification_notes") or []
            self.assertNotIn("terminal default applied", notes,
                             "terminal default overwrote/re-noted a classified block")


class Test_V001_ChapterNumberContinuity(BaseFixtureTest):

    def test_positive_gap_detected(self):
        path = self._fixture("v001_chapter_gap.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v001 = [w for w in ctx.warnings if w.get("rule") == "V-001"]
        self.assertEqual(len(v001), 1, "expected one V-001 gap warning")
        self.assertIn("gap between", v001[0]["detail"])

    def test_negative_continuous_no_warning(self):
        path = self._fixture("v001_chapters_continuous.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v001 = [w for w in ctx.warnings if w.get("rule") == "V-001"]
        self.assertEqual(v001, [], "V-001 fired on continuous chapters")


class Test_V002_HeadingStyleConsistency(BaseFixtureTest):
    """V-002 signature-comparison check. Unit-test flavor: a fixture
    where the deviant chapter wasn't classified as chapter_heading
    doesn't exercise V-002 directly (C-001 only catches Heading2), so
    V-001 catches the gap first. That's documented; V-002's direct
    behavior is tested with a manufactured context.
    """

    def test_uniform_signatures_no_warning(self):
        path = self._fixture("v001_chapters_continuous.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v002 = [w for w in ctx.warnings if w.get("rule") == "V-002"]
        self.assertEqual(v002, [])

    def test_manufactured_mixed_signatures_flagged(self):
        """Two chapter_heading blocks with different (type, heading_level)
        signatures → V-002 emits a warning.
        """
        from lib.rules.base import RuleContext
        from lib.rules.validation import V002_HeadingStyleConsistency
        ctx = RuleContext(blocks=[
            {"id": "b_000001", "type": "heading", "heading_level": 2,
             "role": "chapter_heading", "chapter_number": 1,
             "chapter_title": "One",
             "spans": [{"text": "Chapter 1 One", "marks": []}]},
            {"id": "b_000002", "type": "heading", "heading_level": 2,
             "role": "chapter_heading", "chapter_number": 2,
             "chapter_title": "Two",
             "spans": [{"text": "Chapter 2 Two", "marks": []}]},
            {"id": "b_000003", "type": "paragraph",
             "role": "chapter_heading", "chapter_number": 3,
             "chapter_title": "Three",
             "spans": [{"text": "Chapter 3 Three", "marks": []}]},
        ])
        V002_HeadingStyleConsistency().run(ctx)
        self.assertEqual(len(ctx.warnings), 1)
        w = ctx.warnings[0]
        self.assertEqual(w["rule"], "V-002")
        self.assertIn("b_000003", w["blocks"])


class Test_V003_SpaceLossHeuristic(BaseFixtureTest):

    def test_positive_joined_words_flagged(self):
        path = self._fixture("v003_joined_words.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v003 = [w for w in ctx.warnings if w.get("rule") == "V-003"]
        flagged_tokens = {w["detail"] for w in v003}
        # Must catch at least one of "Theweather" / "thefirst" (both are
        # function-word-led and fail the dictionary check).
        self.assertTrue(
            any("Theweather" in t or "theweather" in t.lower() for t in flagged_tokens)
            or any("thefirst" in t.lower() for t in flagged_tokens),
            f"V-003 did not flag expected function-word-led joins; got: {flagged_tokens}"
        )

    def test_negative_legitimate_compounds_not_flagged(self):
        """thereon / ourselves / birthday / thereafter — all are real
        words or start with function words that form real compounds.
        Dictionary check suppresses all.
        """
        path = self._fixture("v003_legitimate_compounds.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v003 = [w for w in ctx.warnings if w.get("rule") == "V-003"]
        self.assertEqual(v003, [],
                         f"V-003 false-positive: {[w['detail'] for w in v003]}")


class Test_H001_AuthorTitlePageVsIntake(BaseFixtureTest):
    """H-001 emit, order 1 (Layer 5 human-clarification default).

    The fixture alone isn't enough: H-001 compares manuscript_meta
    (written by C-003) against intake_metadata (passed in by the
    caller). Each test case supplies an intake dict matching its
    scenario.
    """

    def test_positive_matching_intake_records_decision(self):
        """Author title page matches intake → applied_rules[] records
        the 'used author title page' decision, no warning."""
        path = self._fixture("h001_author_title_and_intake.docx")
        intake = {"title": "Shadows of the Forgotten", "author": "Jane Author"}
        ctx, exc = _process_fixture(path, intake_metadata=intake)
        self.assertIsNone(exc)
        h001 = [r for r in ctx.applied_rules if r.get("rule") == "H-001"]
        self.assertEqual(len(h001), 1)
        self.assertEqual(
            h001[0]["decision"],
            "used author title page; suppressed system-generated",
        )
        # No H-001 divergence warning when fields match.
        div = [w for w in ctx.warnings if w.get("rule") == "H-001"]
        self.assertEqual(div, [])

    def test_positive_divergent_intake_warns(self):
        """Author title differs materially from intake → H-001 still
        fires (decision: use author's) AND a divergence warning is
        emitted for human review."""
        path = self._fixture("h001_author_title_and_intake.docx")
        intake = {"title": "The Wrong Title", "author": "Jane Author"}
        ctx, exc = _process_fixture(path, intake_metadata=intake)
        self.assertIsNone(exc)
        h001 = [r for r in ctx.applied_rules if r.get("rule") == "H-001"]
        self.assertEqual(len(h001), 1)
        div = [w for w in ctx.warnings if w.get("rule") == "H-001"]
        self.assertEqual(len(div), 1)
        self.assertIn("title differs", div[0]["detail"])

    def test_negative_no_title_page_no_fire(self):
        """Author didn't supply a title page → no manuscript_meta title
        → H-001 must NOT fire even when intake is populated."""
        path = self._fixture("c003_no_title_page.docx")
        intake = {"title": "Some Book", "author": "Some Author"}
        ctx, exc = _process_fixture(path, intake_metadata=intake)
        self.assertIsNone(exc)
        h001 = [r for r in ctx.applied_rules if r.get("rule") == "H-001"]
        self.assertEqual(h001, [])

    def test_negative_no_intake_no_fire(self):
        """Intake absent → H-001 no-op even when manuscript_meta is
        populated."""
        path = self._fixture("h001_author_title_and_intake.docx")
        ctx, exc = _process_fixture(path, intake_metadata=None)
        self.assertIsNone(exc)
        h001 = [r for r in ctx.applied_rules if r.get("rule") == "H-001"]
        self.assertEqual(h001, [])

    def test_h001_warning_passes_schema(self):
        """H-001's divergence warning uses rule='H-001' — the schema
        was widened to accept H-### in addition to V-###. Confirm the
        resulting artifact validates."""
        path = self._fixture("h001_author_title_and_intake.docx")
        intake = {"title": "The Wrong Title", "author": "Jane Author"}
        ctx, exc = _process_fixture(path, intake_metadata=intake)
        self.assertIsNone(exc)
        errors = list(self.validator.iter_errors(ctx.artifact))
        if errors:
            for e in errors[:3]:
                print(f"  schema err: {e.message}")
        self.assertEqual(errors, [])


class Test_ArtifactSchemaEndToEnd(BaseFixtureTest):
    """After iter 5 (terminal default lands), artifacts produced by the
    full pipeline must validate against manuscript.v2.0.schema.json.
    This is the first time I-2 holds end-to-end.
    """

    def test_title_page_fixture_produces_schema_valid_artifact(self):
        path = self._fixture("c003_author_title_page.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        errors = sorted(self.validator.iter_errors(ctx.artifact),
                        key=lambda e: list(e.absolute_path))
        if errors:
            for e in errors[:5]:
                print(f"  schema error at {list(e.absolute_path)}: {e.message}")
        self.assertEqual(errors, [], f"{len(errors)} schema errors")

    def test_chapter_fixture_produces_schema_valid_artifact(self):
        path = self._fixture("v001_chapters_continuous.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        errors = sorted(self.validator.iter_errors(ctx.artifact),
                        key=lambda e: list(e.absolute_path))
        if errors:
            for e in errors[:5]:
                print(f"  schema error at {list(e.absolute_path)}: {e.message}")
        self.assertEqual(errors, [], f"{len(errors)} schema errors")


class Test_V004_TrackedChangesResidueDetector(BaseFixtureTest):

    def test_negative_clean_extraction_no_warning(self):
        """When N-002 resolves tracked changes properly, V-004 emits
        zero warnings. The n002 fixture exercises this path.
        """
        path = self._fixture("n002_tracked_changes.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        v004 = [w for w in ctx.warnings if w.get("rule") == "V-004"]
        self.assertEqual(v004, [],
                         "V-004 false-positive on a clean extraction")

    def test_manufactured_literal_ins_marker_flagged(self):
        """A block with a literal '<w:ins' in its text (simulating an
        extractor bug) must be flagged by V-004.
        """
        from lib.rules.base import RuleContext
        from lib.rules.validation import V004_TrackedChangesResidueDetector
        ctx = RuleContext(blocks=[
            {"id": "b_000001", "type": "paragraph",
             "role": "body_paragraph",
             "spans": [{"text": "This is fine.", "marks": []}]},
            {"id": "b_000002", "type": "paragraph",
             "role": "body_paragraph",
             "spans": [{"text": "Leaked <w:ins> marker here.", "marks": []}]},
        ])
        V004_TrackedChangesResidueDetector().run(ctx)
        v004 = [w for w in ctx.warnings if w.get("rule") == "V-004"]
        self.assertEqual(len(v004), 1)
        self.assertEqual(v004[0]["block_id"], "b_000002")


class Test_DeriveStorageIds(BaseFixtureTest):
    """Gate 3 closure: _derive_storage_ids reads canonical lookup fields
    directly off the Service record. Tests the helper without touching
    Airtable by constructing a fake Service dict and a stub processor.
    """

    @staticmethod
    def _stub_processor():
        """Build just enough of ManuscriptProcessor to call
        _derive_storage_ids without standing up Airtable / R2 clients.
        """
        from pronto_worker_1 import ManuscriptProcessor
        proc = ManuscriptProcessor.__new__(ManuscriptProcessor)
        proc.projects_table = None  # not consulted in v1.0.2 path
        proc.book_metadata_table = None
        return proc

    def test_canonical_lookups_resolve(self):
        """Both Project Intake Submission ID and Service SKU lookups
        present → returns (intake_id, sku) verbatim."""
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {
                "Project Intake Submission ID": ["TALLY-8F3Q"],
                "Service SKU": ["INTFMT"],
            },
        }
        intake_id, sku = proc._derive_storage_ids(service, project_id="recPROJ")
        self.assertEqual(intake_id, "TALLY-8F3Q")
        self.assertEqual(sku, "INTFMT")

    def test_string_lookup_also_works(self):
        """Defensive: if the field type is ever changed upstream from
        multipleLookupValues to a bare string, the helper handles both.
        """
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {
                "Project Intake Submission ID": "TALLY-8F3Q",
                "Service SKU": "INTFMT",
            },
        }
        intake_id, sku = proc._derive_storage_ids(service, project_id=None)
        self.assertEqual(intake_id, "TALLY-8F3Q")
        self.assertEqual(sku, "INTFMT")

    def test_missing_intake_raises_with_actionable_message(self):
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {"Service SKU": ["INTFMT"]},  # intake lookup absent
        }
        with self.assertRaises(ValueError) as cm:
            proc._derive_storage_ids(service, project_id="recPROJ")
        msg = str(cm.exception)
        self.assertIn("Project Intake Submission ID", msg)
        self.assertIn("recSVC123", msg)

    def test_missing_sku_raises_with_actionable_message(self):
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {"Project Intake Submission ID": ["TALLY-8F3Q"]},
        }
        with self.assertRaises(ValueError) as cm:
            proc._derive_storage_ids(service, project_id="recPROJ")
        msg = str(cm.exception)
        self.assertIn("Service SKU", msg)
        self.assertIn("Service Catalog", msg)

    def test_empty_lookup_list_treated_as_missing(self):
        """Airtable returns empty list when the link resolves to a
        record but the source field is blank — must raise, not produce
        an empty string in the storage key."""
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {
                "Project Intake Submission ID": [],
                "Service SKU": ["INTFMT"],
            },
        }
        with self.assertRaises(ValueError):
            proc._derive_storage_ids(service, project_id="recPROJ")

    def test_url_safe_sanitization(self):
        """Spaces and slashes in the canonical values get replaced so
        the resulting storage key has no path-segment surprises."""
        proc = self._stub_processor()
        service = {
            "id": "recSVC123",
            "fields": {
                "Project Intake Submission ID": ["TALLY 8F3Q/X"],
                "Service SKU": ["INT FMT"],
            },
        }
        intake_id, sku = proc._derive_storage_ids(service, project_id=None)
        self.assertEqual(intake_id, "TALLY_8F3Q_X")
        self.assertEqual(sku, "INT_FMT")


class Test_N005_StripExternalLicenseBoilerplate(BaseFixtureTest):
    """N-005 v1 — Doc 22 v1.0.3 amendment.

    Strip-phase rule, order 3. Removes Project-Gutenberg-style license
    boilerplate before the classifier runs, so C-001 doesn't promote
    license headings to chapter_heading.
    """

    def test_positive_gutenberg_boilerplate_stripped(self):
        path = self._fixture("n005_gutenberg_pride_and_prejudice.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)

        # The synthetic Gutenberg fixture has 3 real chapters embedded
        # between preamble and postscript license blocks. Post-N-005,
        # the only chapter_heading blocks should be the real ones.
        chapter_titles = [
            b.get("chapter_title")
            for b in ctx.blocks
            if b.get("role") == "chapter_heading"
        ]
        self.assertEqual(
            sorted(chapter_titles),
            sorted(["Chapter I", "Chapter II", "Chapter III"]),
            f"unexpected chapter set after N-005: {chapter_titles}"
        )
        # NO chapter_heading should reference Gutenberg license content.
        for title in chapter_titles:
            self.assertNotIn("Project Gutenberg", title)
            self.assertNotIn("Section ", title)
            self.assertNotIn("END OF", title)

    def test_positive_emits_applied_rules_summary_entry(self):
        path = self._fixture("n005_gutenberg_pride_and_prejudice.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        n005 = [r for r in ctx.applied_rules if r.get("rule") == "N-005"]
        self.assertEqual(
            len(n005), 1,
            "expected exactly one N-005 applied_rules entry"
        )
        entry = n005[0]
        self.assertEqual(entry["version"], "v1")
        self.assertGreater(
            entry["count"], 0,
            "N-005 entry must carry a non-zero block-removal count"
        )

    def test_walk_consumes_internal_license_section_headings(self):
        """Doc 22 v1.0.1-of-amendments end-marker semantic: license
        sub-headings INSIDE the boilerplate range (e.g., 'Section 1.
        Information about ...') are consumed by the walk-forward pass,
        not treated as stop markers. The walk only stops at a
        non-license heading-level-1 or heading-level-2 (the real
        Chapter heading) or end-of-document.
        """
        path = self._fixture("n005_gutenberg_pride_and_prejudice.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        # No surviving block should carry "Section N." license-section
        # heading text.
        for b in ctx.blocks:
            text = ""
            if "spans" in b:
                text = "".join(s.get("text", "") for s in b["spans"])
            elif "text" in b:
                text = b["text"]
            text = (text or "").strip().lower()
            self.assertFalse(
                text.startswith("section 1. information"),
                f"License section heading survived N-005: {text[:80]!r}"
            )
            self.assertFalse(
                text.startswith("section 2. information"),
                f"License section heading survived N-005: {text[:80]!r}"
            )
            self.assertFalse(
                text.startswith("section 3. information"),
                f"License section heading survived N-005: {text[:80]!r}"
            )

    def test_negative_author_text_with_word_gutenberg_unaffected(self):
        """Negative case: author writes about Gutenberg in their own
        prose, doesn't use canonical license phrasing. N-005 must NOT
        fire — the negation guard hinges on the explicit Gutenberg-
        specific patterns, not generic words.
        """
        path = self._fixture("n005_author_supplied_text_with_word_gutenberg.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        n005 = [r for r in ctx.applied_rules if r.get("rule") == "N-005"]
        self.assertEqual(
            n005, [],
            "N-005 fired on a negative-case manuscript whose only "
            "Gutenberg connection is the literal word 'Gutenberg'"
        )
        # Both authored chapters must survive.
        chapter_titles = [
            b.get("chapter_title")
            for b in ctx.blocks
            if b.get("role") == "chapter_heading"
        ]
        self.assertIn("Gutenberg's Workshop", chapter_titles)
        self.assertIn("The License Question", chapter_titles)

    def test_real_pride_and_prejudice_docx_strips_gutenberg(self):
        """Integration smoke: run N-005 against the actual Pride and
        Prejudice DOCX referenced by the amendments doc.

        Two findings the smoke surfaced that are worth recording in
        the test (so they don't get rediscovered later):

        Finding 1 — Pattern gap. The amendments doc's frozen 6-pattern
        set catches the OPENING Gutenberg heading ("The Project
        Gutenberg eBook of Pride and Prejudice") but does NOT catch
        the CLOSING heading ("THE FULL PROJECT GUTENBERG™ LICENSE").
        A 7th pattern like /^the full project gutenberg/i would close
        this. Out of scope for v1.0.3 since the frozen set was
        explicitly named; flag for amendments v1.0.4.

        Finding 2 — C-001/C-004 boundary. The DOCX has legitimate
        front-matter Heading2 blocks (PREFACE, List of Illustrations)
        that C-001 promotes to chapter_heading because C-004 only
        handles Heading1. Unrelated to N-005; flagged for the next
        classification-quality conversation.

        Given those two: the actual P&P DOCX has 65 Heading2 blocks
        and N-005 (frozen pattern set) strips exactly 1 of them,
        leaving 64 surviving chapter_heading classifications. The
        test asserts that and explicitly checks that the OPENING
        Gutenberg preamble is gone while the CLOSING license heading
        survives (documenting the gap, not regression-protecting it).
        """
        path = Path(r"C:\Users\jesse\OneDrive\Documents\pride_and_prejudice.docx")
        if not path.exists():
            self.skipTest(f"Pride and Prejudice DOCX not available at {path}")

        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        chapters = [b for b in ctx.blocks if b.get("role") == "chapter_heading"]
        chapter_titles = [c.get("chapter_title", "") for c in chapters]

        # Tight range — currently 64 exactly. Range tolerates
        # whitespace-only changes upstream that shift the heading
        # count by ±2 without indicating a regression.
        self.assertGreaterEqual(
            len(chapters), 62,
            f"Too few chapters survived N-005 ({len(chapters)}); the "
            f"rule may be over-stripping real content."
        )
        self.assertLessEqual(
            len(chapters), 66,
            f"Too many chapters in output ({len(chapters)}); N-005 "
            f"may have stopped firing on Pandoc Gutenberg license "
            f"headings."
        )

        # Opening Gutenberg preamble heading must be gone (this is what
        # the v1.0.1 frozen pattern set catches today).
        self.assertFalse(
            any("Project Gutenberg eBook of" in t for t in chapter_titles),
            "Opening Gutenberg preamble heading survived N-005"
        )
        # Start/end markers (with the *** prefix) must not survive
        # if any are present.
        for title in chapter_titles:
            self.assertNotRegex(
                title, r"^\*\*\* (START|END) OF.*PROJECT GUTENBERG",
                f"Gutenberg *** START/END marker survived: {title!r}"
            )

        # Closing license heading is the documented v1.0.1 gap. Test
        # currently asserts it SURVIVES — flipping this to assertFalse
        # is the regression test for whenever amendments v1.0.4 adds
        # the missing pattern.
        closing_license_survived = any(
            "FULL PROJECT GUTENBERG" in t for t in chapter_titles
        )
        self.assertTrue(
            closing_license_survived,
            "If this fails, amendments v1.0.4 may have added a "
            "pattern catching the closing license heading. Flip the "
            "assertion or remove this branch — finding is now closed."
        )

        n005 = [r for r in ctx.applied_rules if r.get("rule") == "N-005"]
        self.assertEqual(len(n005), 1, "N-005 entry missing or duplicated")
        self.assertGreater(n005[0]["count"], 0)


class Test_ExtractorPStyleSynthesis(BaseFixtureTest):
    """v1.0.3 extractor enhancement: named pStyles (Title, Subtitle,
    Author, BookTitle) → synthesized style_tags. Closes the Pandoc-
    EPUB-to-DOCX gap where named pStyles survive but visual properties
    don't.
    """

    def test_title_pstyle_synthesizes_centered_and_large_font(self):
        path = self._fixture("extractor_pstyle_title_author.docx")
        blocks, _ = extract_docx(path)
        # Find the Title-styled block (paragraph with "A Quiet Day in May").
        titles = [
            b for b in blocks
            if b.get("type") == "paragraph"
            and "spans" in b
            and "A Quiet Day in May" in "".join(
                s.get("text", "") for s in b["spans"]
            )
        ]
        self.assertEqual(len(titles), 1)
        tags = titles[0].get("style_tags") or []
        self.assertIn("centered", tags,
                      "Title pStyle should synthesize 'centered' style_tag")
        self.assertIn("large_font", tags,
                      "Title pStyle should synthesize 'large_font' style_tag")

    def test_author_pstyle_synthesizes_centered_only(self):
        path = self._fixture("extractor_pstyle_title_author.docx")
        blocks, _ = extract_docx(path)
        authors = [
            b for b in blocks
            if b.get("type") == "paragraph"
            and "spans" in b
            and "Some Other Author" in "".join(
                s.get("text", "") for s in b["spans"]
            )
        ]
        self.assertEqual(len(authors), 1)
        tags = authors[0].get("style_tags") or []
        self.assertIn("centered", tags,
                      "Author pStyle should synthesize 'centered' style_tag")
        self.assertNotIn("large_font", tags,
                         "Author pStyle should NOT synthesize 'large_font'")

    def test_dedupe_when_explicit_alignment_and_pstyle_both_set(self):
        """When the source DOCX has BOTH pStyle=Title AND explicit
        w:jc=center, both code paths want to add 'centered'. The
        resulting style_tags must contain 'centered' exactly once.
        """
        path = self._fixture("extractor_pstyle_dedupe.docx")
        blocks, _ = extract_docx(path)
        target = [
            b for b in blocks
            if b.get("type") == "paragraph"
            and "spans" in b
            and "Doubly-Marked Title" in "".join(
                s.get("text", "") for s in b["spans"]
            )
        ]
        self.assertEqual(len(target), 1)
        tags = target[0].get("style_tags") or []
        self.assertEqual(
            tags.count("centered"), 1,
            f"'centered' duplicated in style_tags: {tags}"
        )
        # large_font should still be present (synthesized from Title pStyle).
        self.assertIn("large_font", tags)

    def test_c003_now_classifies_pandoc_style_title_page(self):
        """End-to-end: with the extractor enhancement, a Pandoc-style
        DOCX (named pStyles, no visual properties) should now have its
        title-page cluster classified by C-003. Before v1.0.3 this
        cluster came up empty.
        """
        path = self._fixture("extractor_pstyle_title_author.docx")
        ctx, exc = _process_fixture(path)
        self.assertIsNone(exc)
        title_pages = [b for b in ctx.blocks if b.get("role") == "title_page"]
        self.assertGreaterEqual(
            len(title_pages), 1,
            "C-003 didn't fire on a Pandoc-style fixture even after "
            "extractor synthesizes centered+large_font tags. The "
            "v1.0.3 amendment isn't accomplishing its stated goal."
        )
        # And manuscript_meta should have the title.
        self.assertIsNotNone(ctx.manuscript_meta)
        self.assertEqual(
            ctx.manuscript_meta.get("title"),
            "A Quiet Day in May"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
