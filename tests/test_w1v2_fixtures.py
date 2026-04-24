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
RULES_VERSION = "1.0.1"


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
            "services/TALLY-8F3Q/INTFMT/manuscript/v2.0/w5.0.0a1-r1.0.1/manuscript.json",
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
