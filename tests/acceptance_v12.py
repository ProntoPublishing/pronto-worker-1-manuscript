"""Rules-1.2 acceptance runner — Gate 2 rulings Q1/Q3 (2026-07-16).

Book 16 (test 21's unstructured Frankenstein) is THE acceptance
fixture; Book 17 is Book 16 with a fake plain-text contents block
prepended (shape (b); the source already carries shape (a) inline).

    python tests/acceptance_v12.py [--out <dir>]

Rows:
  16.1  28 landmarks promoted (Letter 1-4 + Chapter 1-24), 0 parts
  16.2  V-005 SILENT (structure was found)
  16.3  V-006 fires, severity medium (training wheels -> Review gate)
  16.4  source TOC (shape a) + its CONTENTS label suppressed as
        role=structural subtype=source_toc
  16.5  schema 2.1 valid, zero rule faults
  17.1  fake TOC detected + suppressed (shape (b) run + label)
  17.2  landmark count still 28 — zero fake landmarks at the front
        (no chapter_heading before the real "Letter 1" opener)
  17.3  V-006 fires / V-005 silent / schema valid / zero faults

Exit 0 = every row passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import jsonschema

from lib.cir import extract_docx
from lib.pipeline import run_phase
from lib.rules.base import RuleContext
from lib.emit import build_artifact, compute_source_hash

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "manuscript" / "manuscript.v2.1.schema.json"

from w1_local import WORKER_VERSION, RULES_VERSION  # single source of truth

BOOKS = {
    "book16": r"C:\Users\Jesse Pope\Projects\corpus_sources\frankenstein_unstructured.docx",
    "book17": r"C:\Users\Jesse Pope\Projects\corpus_sources\frankenstein_unstructured_toc.docx",
}


def run_book(path: Path):
    """Mirror acceptance_v11's run_book (no intake — H-001 stays off)."""
    started = datetime.now(timezone.utc)
    ctx = RuleContext(blocks=[], intake_metadata=None)
    factory_args = {"source_path": str(path)}
    run_phase("ingest", ctx, factory_args=factory_args)
    blocks, _ = extract_docx(str(path))
    ctx.blocks = blocks
    for phase in ("strip", "classify", "normalize", "validate", "emit"):
        run_phase(phase, ctx, factory_args=factory_args)
    finished = datetime.now(timezone.utc)
    artifact = build_artifact(
        ctx_blocks=ctx.blocks,
        ctx_applied_rules=ctx.applied_rules,
        ctx_warnings=ctx.warnings,
        ctx_rule_faults=ctx.rule_faults,
        worker_version=WORKER_VERSION,
        rules_version=RULES_VERSION,
        service_id="acceptance",
        project_id="acceptance",
        source_meta={
            "original_filename": path.name,
            "original_format": "docx",
            "original_file_size_bytes": path.stat().st_size,
            "source_hash_sha256": compute_source_hash(path),
            "ingested_at": started.isoformat(),
        },
        processed_at=finished,
        processing_time_seconds=(finished - started).total_seconds(),
        dry_run=True,
        manuscript_meta=ctx.manuscript_meta,
    )
    return ctx, artifact


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / ".acceptance_out")
    args = ap.parse_args()
    args.out.mkdir(exist_ok=True)

    validator = jsonschema.Draft7Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    rows = []

    def row(rid, desc, ok, detail=""):
        rows.append((rid, desc, bool(ok), str(detail)))

    results = {}
    for key, src in BOOKS.items():
        print(f"--- {key}: {Path(src).name}", flush=True)
        ctx, artifact = run_book(Path(src))
        (args.out / f"{key}.manuscript.json").write_text(
            json.dumps(artifact, indent=1), encoding="utf-8")
        results[key] = (ctx, artifact)

    for key, (ctx, artifact) in results.items():
        blocks = artifact["content"]["blocks"]
        chapters = [b for b in blocks if b.get("role") == "chapter_heading"]
        parts = [b for b in blocks if b.get("role") == "part_divider"]
        toc = [b for b in blocks
               if b.get("role") == "structural"
               and b.get("subtype") == "source_toc"]
        warnings = artifact.get("warnings", [])
        v005 = [w for w in warnings if w.get("rule") == "V-005"]
        v006 = [w for w in warnings if w.get("rule") == "V-006"]
        letters = [b for b in chapters
                   if (b.get("chapter_title") or "").lower().startswith("letter")]
        errors = sorted(validator.iter_errors(artifact),
                        key=lambda e: e.json_path)[:3]

        print(json.dumps({
            "book": key,
            "blocks": len(blocks),
            "chapters": len(chapters),
            "letters": len(letters),
            "parts": len(parts),
            "source_toc_blocks": len(toc),
            "warnings_by_rule": {
                r: sum(1 for w in warnings if w.get("rule") == r)
                for r in sorted({w.get("rule") for w in warnings})
            },
            "rule_faults": len(artifact.get("rule_faults", [])),
            "schema_ok": not errors,
        }), flush=True)

        n = key[-2:]
        row(f"{n}.1", "28 landmarks (4 letters + 24 chapters), 0 parts",
            len(chapters) == 28 and len(letters) == 4 and not parts,
            f"chapters={len(chapters)}, letters={len(letters)}, parts={len(parts)}")
        row(f"{n}.2", "V-005 silent",
            not v005, f"v005={len(v005)}")
        row(f"{n}.3", "V-006 fires at medium (training wheels)",
            len(v006) == 1 and v006[0].get("severity") == "medium",
            v006[0].get("detail", "")[:100] if v006 else "MISSING")
        row(f"{n}.5", "schema 2.1 valid + zero rule faults",
            not errors and not artifact.get("rule_faults"),
            errors[0].message[:80] if errors else "clean")

    # Book-specific TOC rows.
    b16_toc = [b for b in results["book16"][1]["content"]["blocks"]
               if b.get("subtype") == "source_toc"]
    row("16.4", "source TOC (shape a) + label suppressed",
        len(b16_toc) == 2,  # inline block + CONTENTS label
        f"source_toc blocks={len(b16_toc)}")

    b17_blocks = results["book17"][1]["content"]["blocks"]
    b17_toc = [b for b in b17_blocks if b.get("subtype") == "source_toc"]
    # Fake label + 28 fake entries + original label + original inline = 31.
    row("17.4", "fake TOC (shape b) + originals suppressed",
        len(b17_toc) == 31, f"source_toc blocks={len(b17_toc)}")
    first_real = next(
        (i for i, b in enumerate(b17_blocks)
         if b.get("role") == "chapter_heading"), None)
    fake_landmarks_front = [
        b for b in b17_blocks[:first_real or 0]
        if b.get("role") in ("chapter_heading", "part_divider")
    ]
    # Every source_toc block must sit BEFORE the first chapter_heading:
    # zero fake landmarks at the front of the book.
    toc_after_first = [
        i for i, b in enumerate(b17_blocks)
        if b.get("subtype") == "source_toc"
        and first_real is not None and i > first_real
    ]
    row("17.2b", "zero fake landmarks at the front",
        first_real is not None and not toc_after_first,
        f"first chapter_heading at block index {first_real}; "
        f"toc blocks after it: {len(toc_after_first)}")

    width = max(len(r[1]) for r in rows)
    failed = sum(1 for r in rows if not r[2])
    for rid, desc, ok, detail in rows:
        print(f"  {rid:<6} {desc:<{width}}  {'PASS' if ok else 'FAIL'}  {detail[:100]}")
    print(f"\n=== {len(rows) - failed}/{len(rows)} rows pass ===")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
