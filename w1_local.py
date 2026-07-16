"""
Local W1 pipeline driver — DOCX → manuscript.v2.0.json, no Airtable/R2.

Runs the exact deployed pipeline (ingest → strip → classify → normalize →
validate → emit) on a local DOCX. Corpus-testing tool; untracked.

Usage:
    python w1_local.py <input.docx> <output.json> [--title T] [--author A]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.cir import extract_docx
from lib.pipeline import run_phase
from lib.rules.base import RuleContext, PHASES
from lib.rules.rejection import RuleRejectException
from lib.emit import build_artifact, compute_source_hash

WORKER_VERSION = "5.2.1-a1"   # matches deployed main (rules 1.2 + break observation)
RULES_VERSION = "1.2"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("docx", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--title", default=None)
    ap.add_argument("--author", default=None)
    args = ap.parse_args()

    started = datetime.now(timezone.utc)
    intake = None
    if args.title or args.author:
        intake = {"title": args.title, "author": args.author}

    ctx = RuleContext(blocks=[], intake_metadata=intake)
    factory_args = {"source_path": str(args.docx)}

    try:
        run_phase("ingest", ctx, factory_args=factory_args)
    except RuleRejectException as e:
        print(f"REJECTED by {e.rule_id}: {e.message}")
        return 1

    blocks, extra_source = extract_docx(str(args.docx))
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
        service_id="local",
        project_id="local",
        source_meta={
            "original_filename": args.docx.name,
            "original_format": "docx",
            "original_file_size_bytes": args.docx.stat().st_size,
            "source_hash_sha256": compute_source_hash(args.docx),
            "ingested_at": started.isoformat(),
        },
        processed_at=finished,
        processing_time_seconds=(finished - started).total_seconds(),
        dry_run=True,
        manuscript_meta=ctx.manuscript_meta,
    )

    args.out.write_text(json.dumps(artifact, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    roles = {}
    for b in ctx.blocks:
        roles[b.get("role")] = roles.get(b.get("role"), 0) + 1
    print(json.dumps({
        "blocks": len(ctx.blocks),
        "roles": roles,
        "applied_rules": [
            {k: r[k] for k in ("rule", "count") if k in r} for r in ctx.applied_rules
        ],
        "warnings": len(ctx.warnings),
        "rule_faults": len(ctx.rule_faults),
        "manuscript_meta": ctx.manuscript_meta,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
