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

    def test_empty_paragraph_runs_collapsed(self):
        """N-001 paragraph-level extension — the extractor collapses runs
        of 2+ empty paragraphs to a single empty_line block.
        """
        path = self._fixture("n001_double_spaces.docx")
        blocks, _ = extract_docx(path)
        empty_runs = 0
        streak = 0
        for b in blocks:
            if b["type"] == "paragraph" and "empty_line" in (b.get("style_tags") or []):
                streak += 1
                if streak > 1:
                    empty_runs += 1
            else:
                streak = 0
        self.assertEqual(empty_runs, 0, "consecutive empty paragraphs not collapsed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
