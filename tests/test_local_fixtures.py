"""
Local fixture diff tests — the primary corpus-level test loop for W1.

What this is
  Five real manuscripts (one AI-generated, four Project-Gutenberg-sourced)
  live under tests/fixtures/local/. For each book we have an input.docx
  and a golden.manuscript.v2.json. This test runs the pure pipeline
  (lib.local_runner.run_local) against each input and asserts the
  freshly-built artifact is byte-identical to the golden.

Why
  Synthetic per-rule fixtures (tests/fixtures/v1/) prove a rule does what
  it says. Real-corpus diff tests prove the rules in combination produce
  the same output run-to-run. When you intentionally change behavior, you
  re-generate the goldens (`python pronto_worker_1.py --local --input
  tests/fixtures/local/<book>/input.docx --output
  tests/fixtures/local/<book>/golden.manuscript.v2.json`) and the diff
  shows exactly what changed in the output. That diff IS the change-
  review artifact.

Determinism
  run_local(deterministic=True) pins run_id, artifact_id, and all
  timestamps. Source-content-derived fields (source_hash_sha256,
  block ids, etc.) are deterministic given the same DOCX bytes. So the
  expected diff against an unchanged golden is literally zero.
"""
from __future__ import annotations
import json
import unittest
from pathlib import Path
from typing import Any, Dict, List

# Use the same constants the production code uses, so a mismatch caught
# by these tests reflects the actual artifact a deployed worker would
# emit.
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from lib.local_runner import run_local  # noqa: E402
from pronto_worker_1 import WORKER_VERSION, RULES_VERSION  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "local"

# Books in the golden corpus. Each must have input.docx + the golden
# JSON sibling. Adding a book = create the dir, drop the DOCX, run the
# `--local` CLI to produce the golden, append the slug here.
GOLDEN_BOOKS = (
    "the_hatch_list",
    "pride_and_prejudice",
    "frankenstein",
    "jekyll_and_hyde",
    "dracula",
)


def _diff_summary(produced: Dict[str, Any], golden: Dict[str, Any]) -> str:
    """Compose a short human-readable summary of where a produced
    artifact diverges from its golden. Helps a failing test point at
    the right place without dumping the full 2000-block JSON.
    """
    lines: List[str] = []

    # Top-level scalar fields that should never drift.
    for k in ("schema_version", "worker_version", "rules_version",
              "artifact_id", "service_id"):
        if produced.get(k) != golden.get(k):
            lines.append(f"  {k}: produced={produced.get(k)!r} golden={golden.get(k)!r}")

    # processing.run_id / processed_at — pinned in deterministic mode.
    pp, gp = produced.get("processing", {}), golden.get("processing", {})
    for k in ("run_id", "processed_at", "project_id"):
        if pp.get(k) != gp.get(k):
            lines.append(f"  processing.{k}: produced={pp.get(k)!r} golden={gp.get(k)!r}")

    # Block count. A delta here is the most common failure mode.
    p_blocks = (produced.get("content") or {}).get("blocks") or []
    g_blocks = (golden.get("content") or {}).get("blocks") or []
    if len(p_blocks) != len(g_blocks):
        lines.append(
            f"  blocks: produced={len(p_blocks)} golden={len(g_blocks)} "
            f"(delta={len(p_blocks) - len(g_blocks):+d})"
        )

    # applied_rules / warnings / rule_faults counts.
    for k in ("applied_rules", "warnings", "rule_faults"):
        pn = len(produced.get(k) or [])
        gn = len(golden.get(k) or [])
        if pn != gn:
            lines.append(f"  {k}: produced={pn} golden={gn} (delta={pn-gn:+d})")

    # If counts agree, look for the first block whose payload differs.
    if len(p_blocks) == len(g_blocks):
        for i, (pb, gb) in enumerate(zip(p_blocks, g_blocks)):
            if pb != gb:
                pid = pb.get("id", f"#{i}")
                lines.append(
                    f"  first-divergent block: idx={i} id={pid} "
                    f"role(p={pb.get('role')!r}, g={gb.get('role')!r}) "
                    f"type(p={pb.get('type')!r}, g={gb.get('type')!r})"
                )
                break
    return "\n".join(lines) if lines else "  (no obvious top-level divergence — payload-level diff)"


class Test_LocalFixtures(unittest.TestCase):
    """Run the W1 pipeline against each fixture and diff against golden."""

    def _check(self, book: str) -> None:
        book_dir = FIXTURES / book
        input_docx = book_dir / "input.docx"
        golden_path = book_dir / "golden.manuscript.v2.json"
        self.assertTrue(input_docx.exists(),
                        f"missing fixture input: {input_docx}")
        self.assertTrue(golden_path.exists(),
                        f"missing fixture golden: {golden_path}")

        result = run_local(
            input_path=input_docx,
            output_path=None,  # in-memory only; we diff against golden
            deterministic=True,
            worker_version=WORKER_VERSION,
            rules_version=RULES_VERSION,
        )

        self.assertFalse(
            result.rejected,
            f"{book} unexpectedly rejected: "
            f"{result.rejection_rule}: {result.rejection_message}",
        )
        self.assertIsNotNone(
            result.artifact, f"{book} produced no artifact"
        )

        with open(golden_path, "r", encoding="utf-8") as f:
            golden = json.load(f)

        if result.artifact != golden:
            self.fail(
                f"{book}: produced artifact diverges from golden.\n"
                f"{_diff_summary(result.artifact, golden)}\n"
                f"To accept the new output as the golden, run:\n"
                f"  python pronto_worker_1.py --local "
                f"--input tests/fixtures/local/{book}/input.docx "
                f"--output tests/fixtures/local/{book}/golden.manuscript.v2.json"
            )

    def test_the_hatch_list(self) -> None:
        """Hatch List — AI-generated original, no Gutenberg shape."""
        self._check("the_hatch_list")

    def test_pride_and_prejudice(self) -> None:
        """P&P — Project Gutenberg #1342, exercises N-005 + C-003."""
        self._check("pride_and_prejudice")

    def test_frankenstein(self) -> None:
        """Frankenstein — Project Gutenberg, epistolary frame."""
        self._check("frankenstein")

    def test_jekyll_and_hyde(self) -> None:
        """Jekyll & Hyde — Project Gutenberg, short Victorian novella."""
        self._check("jekyll_and_hyde")

    def test_dracula(self) -> None:
        """Dracula — Project Gutenberg, long-form epistolary."""
        self._check("dracula")


class Test_LocalRunnerDeterminism(unittest.TestCase):
    """Sanity check: the deterministic-mode contract holds — repeated
    runs against the same input produce the same artifact bytes.
    """

    def test_repeated_runs_produce_identical_artifact(self) -> None:
        # Use the smallest fixture for speed.
        input_docx = FIXTURES / "the_hatch_list" / "input.docx"
        if not input_docx.exists():  # pragma: no cover
            self.skipTest(f"fixture not present: {input_docx}")

        a = run_local(
            input_path=input_docx, output_path=None, deterministic=True,
            worker_version=WORKER_VERSION, rules_version=RULES_VERSION,
        ).artifact
        b = run_local(
            input_path=input_docx, output_path=None, deterministic=True,
            worker_version=WORKER_VERSION, rules_version=RULES_VERSION,
        ).artifact
        self.assertEqual(
            json.dumps(a, sort_keys=True),
            json.dumps(b, sort_keys=True),
            "Two deterministic-mode runs produced different artifacts. "
            "Either a non-deterministic field slipped past the local "
            "runner, or the pipeline itself is non-deterministic.",
        )

    def test_pinned_fields_match_constants(self) -> None:
        """The pinned field values must match the constants exposed by
        local_runner — drift between the two would be silent.
        """
        from lib.local_runner import (
            DETERMINISTIC_RUN_ID,
            DETERMINISTIC_ARTIFACT_ID,
            DETERMINISTIC_TIMESTAMP_STR,
            DETERMINISTIC_SERVICE_ID,
            DETERMINISTIC_PROJECT_ID,
        )
        input_docx = FIXTURES / "the_hatch_list" / "input.docx"
        if not input_docx.exists():  # pragma: no cover
            self.skipTest(f"fixture not present: {input_docx}")

        artifact = run_local(
            input_path=input_docx, output_path=None, deterministic=True,
            worker_version=WORKER_VERSION, rules_version=RULES_VERSION,
        ).artifact
        self.assertEqual(artifact["artifact_id"], DETERMINISTIC_ARTIFACT_ID)
        self.assertEqual(artifact["service_id"], DETERMINISTIC_SERVICE_ID)
        self.assertEqual(artifact["processing"]["run_id"], DETERMINISTIC_RUN_ID)
        self.assertEqual(artifact["processing"]["project_id"], DETERMINISTIC_PROJECT_ID)
        self.assertEqual(artifact["processing"]["processed_at"], DETERMINISTIC_TIMESTAMP_STR)
        self.assertEqual(artifact["source"]["ingested_at"], DETERMINISTIC_TIMESTAMP_STR)


if __name__ == "__main__":
    unittest.main()
