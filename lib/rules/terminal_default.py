"""
Terminal Default — CIR-type → role mapping applied at the end of the
Classify phase.

Per Doc 22 v1.0.2 Patch 1: when a block reaches the end of the Classify
phase and no classifier has assigned a role, it receives a terminal-
default role drawn from the mapping table, and a classification_notes[]
entry is added.

This is operational policy, not a Layer 2 rule. The mapping is W1-owned;
the schema validates only that the resulting role is in the Layer 2 enum.
Mapping violations at runtime (i.e., a CIR type without an entry here)
are written to rule_faults[].
"""
from __future__ import annotations
from typing import Dict

from .base import RuleContext


# Authoritative mapping from Doc 22 v1.0.2 Patch 1. Keys match
# manuscript.v2.0.schema.json block.type.enum; values match
# block.role.enum.
CIR_TYPE_TO_ROLE: Dict[str, str] = {
    "paragraph":          "body_paragraph",
    "heading":            "heading",
    "list_item":          "list_item",
    "table":              "table",
    "image":              "image",
    "code":               "code_block",
    "preformatted_block": "code_block",
    "footnote":           "footnote",
    "blockquote":         "blockquote",
    "page_break":         "structural",
    "horizontal_rule":    "structural",
}


def apply_terminal_default(ctx: RuleContext) -> None:
    """Assign a role to every block that a classifier didn't touch.

    Per Doc 22 v1.0.2: role = CIR_TYPE_TO_ROLE[block.type]; append a
    classification_notes[] entry stating "terminal default applied."
    Any block with an existing non-null role is left alone (I-10-style
    deference, even though terminal default runs after all L2 rules).

    A block whose CIR type has no entry in the mapping table produces a
    rule_faults[] entry and is left role-less — the downstream schema
    validator will then reject the artifact per I-2. This keeps the
    mapping explicit: a new CIR type must be accompanied by a mapping
    entry.
    """
    for block in ctx.blocks:
        if block.get("role"):
            continue
        cir_type = block.get("type")
        mapped = CIR_TYPE_TO_ROLE.get(cir_type)
        if mapped is None:
            ctx.rule_faults.append({
                "rule": "terminal_default",
                "phase": "classify",
                "fault_class": "MappingMissing",
                "message": (
                    f"no terminal-default role mapping for CIR type "
                    f"{cir_type!r}; Doc 22 v1.0.2 mapping table needs "
                    f"an entry."
                ),
                "block_id": block.get("id"),
            })
            continue
        block["role"] = mapped
        notes = block.setdefault("classification_notes", [])
        notes.append("terminal default applied")
