"""
§6 acceptance runner — amendment spec v2.2 + v2.2.1 rulings.

Runs the full local pipeline on the six corpus books and evaluates
every §6 row it can check mechanically. Not a pytest module (the six
sources live outside the repo); invoke directly:

    python tests/acceptance_v11.py [--sources <dir-overrides>] [--out <dir>]

Writes one artifact JSON per book plus acceptance_report.json to --out
(default .acceptance_out/). Exit code 0 = every checked row passed.
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
from lib.rules.rejection import RuleRejectException
from lib.emit import build_artifact, compute_source_hash

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "manuscript" / "manuscript.v2.1.schema.json"

from w1_local import WORKER_VERSION, RULES_VERSION  # single source of truth

BOOKS = {
    "hatch":  r"C:\Users\Jesse Pope\OneDrive\Documents\the_hatch_list.docx",
    "pp":     r"C:\Users\Jesse Pope\OneDrive\Documents\pride_and_prejudice.docx",
    "frank":  r"C:\Users\Jesse Pope\Projects\corpus_sources\frankenstein_1818.docx",
    "dq":     r"C:\Users\Jesse Pope\Projects\corpus_sources\don_quixote_v1.docx",
    "leaves": r"C:\Users\Jesse Pope\Projects\corpus_sources\leaves_of_grass.docx",
    "carol":  r"C:\Users\Jesse Pope\Projects\corpus_sources\christmas_carol.docx",
}

# Hatch's title page carries NO byline (title / ornament / 3-line
# subtitle / city / year) — the §6 "Claude Cumberbatch" author is Book
# 01's INTAKE author, reachable only through H-001 reconciliation.
# Premise mismatch flagged in MIGRATION_NOTES; the row is checked via
# intake + H-001 here.
INTAKE = {
    "hatch": {"title": "The Hatch List", "author": "Claude Cumberbatch"},
}


def run_book(path: Path, intake=None):
    started = datetime.now(timezone.utc)
    ctx = RuleContext(blocks=[], intake_metadata=intake)
    factory_args = {"source_path": str(path)}
    try:
        run_phase("ingest", ctx, factory_args=factory_args)
    except RuleRejectException as e:
        raise SystemExit(f"{path.name}: REJECTED by {e.rule_id}: {e.message}")
    blocks, _, _fm = extract_docx(str(path))
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


def summarize(ctx, artifact):
    blocks = ctx.blocks
    chapters = [b for b in blocks if b.get("role") == "chapter_heading"]
    parts = [b for b in blocks if b.get("role") == "part_divider"]
    subs = [b for b in blocks if b.get("role") == "chapter_subtitle"]
    roles = {}
    for b in blocks:
        roles[b.get("role")] = roles.get(b.get("role"), 0) + 1
    warn_by_rule = {}
    for w in ctx.warnings:
        warn_by_rule[w.get("rule")] = warn_by_rule.get(w.get("rule"), 0) + 1
    n005 = next((r for r in ctx.applied_rules if r.get("rule") == "N-005"), None)
    # per-part chapter number scopes
    scopes, cur = [[]], "start"
    for b in blocks:
        if b.get("role") == "part_divider":
            scopes.append([])
        elif b.get("role") == "chapter_heading" and isinstance(
                b.get("chapter_number"), int):
            scopes[-1].append(b["chapter_number"])
    return {
        "blocks": len(blocks),
        "roles": roles,
        "chapters": len(chapters),
        "chapter_numbers_by_scope": scopes,
        "chapters_with_trailing_title": sum(
            1 for c in chapters
            if c.get("chapter_title")
            and not any("synthesized" in n for n in
                        c.get("classification_notes") or [])
            and c.get("chapter_number") is not None
        ),
        "parts": len(parts),
        "part_titles": [p.get("part_title") for p in parts][:40],
        "subtitles": len(subs),
        "subtitle_texts": [
            "".join(s.get("text", "") for s in b.get("spans", []))[:60]
            for b in subs][:10],
        "manuscript_meta": ctx.manuscript_meta,
        "c003_mechanism": ctx.extras.get("c003_mechanism"),
        "warnings_by_rule": warn_by_rule,
        "warning_count_airtable": len(ctx.warnings),
        "v003_observations": len(ctx.extras.get("v003_observations", [])),
        "rule_faults": len(ctx.rule_faults),
        "n005_removed": (n005 or {}).get("count", 0),
        "schema_version": artifact.get("schema_version"),
        "h001_decision": next(
            (r for r in ctx.applied_rules if r.get("rule") == "H-001"), None),
    }


def check_rows(s):
    """§6 rows → (row, passed, detail). Mechanical checks only; the W2
    render rows are verified separately with the W2 prereq branch."""
    rows = []

    def row(book, name, ok, detail=""):
        rows.append({"book": book, "row": name, "pass": bool(ok),
                     "detail": str(detail)})

    h = s["hatch"]
    row("hatch", "9/9 chapters numbered 1-9",
        h["chapters"] == 9 and [n for sc in h["chapter_numbers_by_scope"]
                                for n in sc] == list(range(1, 10)),
        h["chapter_numbers_by_scope"])
    meta = h["manuscript_meta"] or {}
    row("hatch", "meta title extracted from manuscript",
        (meta.get("title") or "").strip().lower() == "the hatch list",
        meta)
    row("hatch",
        "author via H-001 intake reconciliation "
        "(REINTERPRETED — no byline in source; flagged)",
        h.get("h001_decision") is not None
        and meta.get("author") in (None, "Claude Cumberbatch"),
        f"manuscript author={meta.get('author')!r}; "
        f"H-001={h.get('h001_decision')}")
    row("hatch", "subtitles -> chapter_subtitle", h["subtitles"] > 0,
        f"{h['subtitles']}: {h['subtitle_texts']}")
    row("hatch", "zero-structure silent",
        "V-005" not in h["warnings_by_rule"], h["warnings_by_rule"])

    p = s["pp"]
    nums = [n for sc in p["chapter_numbers_by_scope"] for n in sc]
    row("pp", "61/61 preserved",
        p["chapters"] == 61 and nums == list(range(1, 62)),
        f"{p['chapters']} chapters; numbers ok={nums == list(range(1, 62))}")
    row("pp", "frontmatter not chapters (junk=0 post-N-005)",
        p["chapters"] == 61 and p["n005_removed"] > 0,
        f"N-005 removed {p['n005_removed']} blocks")
    row("pp", "meta extracted + mechanism named",
        bool((p["manuscript_meta"] or {}).get("title"))
        and p["c003_mechanism"] is not None,
        f"meta={p['manuscript_meta']} via {p['c003_mechanism']}")

    f = s["frank"]
    row("frank", "27/27 chapters", f["chapters"] == 27, f["chapters"])
    row("frank", "3 volumes -> part_divider", f["parts"] == 3,
        f["part_titles"])
    row("frank", "per-volume numbering, V-001 silent",
        "V-001" not in f["warnings_by_rule"],
        f["chapter_numbers_by_scope"])
    row("frank", "meta extracted",
        bool((f["manuscript_meta"] or {}).get("title")),
        f["manuscript_meta"])

    d = s["dq"]
    row("dq", "126/126 chapters", d["chapters"] == 126, d["chapters"])
    row("dq", "trailing titles extracted",
        d["chapters_with_trailing_title"] >= 120,
        d["chapters_with_trailing_title"])
    row("dq", "Volume II -> part_divider (2.3 precedence)",
        d["parts"] >= 1 and any("volume" in (t or "").lower()
                                or "II" in (t or "")
                                for t in d["part_titles"]),
        d["part_titles"])
    row("dq", "implicit-Volume-I scoping, V-001 silent",
        "V-001" not in d["warnings_by_rule"],
        [len(v) for v in d["chapter_numbers_by_scope"]])
    row("dq", "0 faults", d["rule_faults"] == 0, d["rule_faults"])

    l = s["leaves"]
    row("leaves", "0 chapters", l["chapters"] == 0, l["chapters"])
    row("leaves", "34 part_dividers", l["parts"] == 34, l["parts"])
    row("leaves", "poem titles -> heading",
        l["roles"].get("heading", 0) > 300, l["roles"].get("heading"))
    row("leaves", "zero-structure silent",
        "V-005" not in l["warnings_by_rule"], l["warnings_by_rule"])

    c = s["carol"]
    cnums = [n for sc in c["chapter_numbers_by_scope"] for n in sc]
    row("carol", "5/5 staves numbered",
        c["chapters"] == 5 and cnums == [1, 2, 3, 4, 5], cnums)
    row("carol", "stave names -> chapter_subtitle", c["subtitles"] >= 5,
        f"{c['subtitles']}: {c['subtitle_texts']}")
    row("carol", "meta extracted",
        bool((c["manuscript_meta"] or {}).get("title")),
        c["manuscript_meta"])

    for book, x in s.items():
        row(book, "schema validates at v2.1",
            x.get("schema_ok"), x.get("schema_error", ""))
        row(book, "V-003 out of Warning Count",
            "V-003" not in x["warnings_by_rule"],
            f"observations={x['v003_observations']}")
    return rows


def enumerate_scopes(scopes):
    return {f"scope{i}": v for i, v in enumerate(scopes)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=REPO_ROOT / ".acceptance_out")
    args = ap.parse_args()
    args.out.mkdir(exist_ok=True)

    validator = jsonschema.Draft7Validator(
        json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))

    summaries = {}
    for key, src in BOOKS.items():
        path = Path(src)
        print(f"--- {key}: {path.name}", flush=True)
        ctx, artifact = run_book(path, intake=INTAKE.get(key))
        summ = summarize(ctx, artifact)
        errors = sorted(validator.iter_errors(artifact),
                        key=lambda e: e.json_path)[:3]
        summ["schema_ok"] = not errors
        if errors:
            summ["schema_error"] = f"{errors[0].json_path}: {errors[0].message[:160]}"
        summaries[key] = summ
        (args.out / f"{key}.manuscript.json").write_text(
            json.dumps(artifact, indent=1, ensure_ascii=False),
            encoding="utf-8")
        print(json.dumps({k: summ[k] for k in (
            "blocks", "chapters", "parts", "subtitles", "n005_removed",
            "warnings_by_rule", "rule_faults", "c003_mechanism",
            "manuscript_meta", "schema_ok")}, ensure_ascii=False),
            flush=True)

    rows = check_rows(summaries)
    report = {"summaries": summaries, "rows": rows}
    (args.out / "acceptance_report.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")

    failed = [r for r in rows if not r["pass"]]
    print(f"\n=== {len(rows) - len(failed)}/{len(rows)} rows pass ===")
    for r in failed:
        print(f"FAIL [{r['book']}] {r['row']} — {r['detail'][:200]}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
