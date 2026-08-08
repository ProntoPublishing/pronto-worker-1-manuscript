import sys
from pathlib import Path
sys.path.insert(0, str(Path(".").resolve()))
from lib.rules.base import RuleContext
from lib.pipeline import run_phase

def blk(bid, text, tags, typ="paragraph"):
    return {"id": bid, "type": typ,
            "spans": [{"text": text, "marks": []}],
            "style_tags": tags}

# Fixture zero — the V-007 pathology: page break between the title
# cluster and the dedication was DROPPED in docx->json, so the
# dedication arrives as a contiguous centered block.
blocks = [
    blk("b_000001", "THE SWALLOW'S RETURN", ["centered", "large_font"]),
    blk("b_000002", "a novel", ["centered"]),
    blk("b_000003", "Wren Calloway", ["centered"]),
    # dropped page break would sit here
    blk("b_000004",
        "For everyone who ever hit send too late — and for the town that bet on them anyway.",
        ["centered"]),  # italic, centered, headingless
    {"id": "b_000005", "type": "paragraph",
     "spans": [{"text": "Chapter One: The Book of Common Wagers", "marks": []}],
     "style_tags": []},
    {"id": "b_000006", "type": "paragraph",
     "spans": [{"text": "It was the kind of morning the town would later swear it had seen coming, though not one of them had said so aloud. " * 3, "marks": []}],
     "style_tags": []},
]
ctx = RuleContext(blocks=blocks)
run_phase("classify", ctx)
print("=== roles after classify ===")
for b in ctx.blocks:
    t = "".join(s.get("text","") for s in b.get("spans", []))[:44]
    print(f'{b["id"]}  role={b.get("role")!r:26}  {t!r}')
