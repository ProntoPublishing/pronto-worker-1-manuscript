"""
Rule base and shared types.

A Rule is anything with a `run(ctx)` method that operates on a shared
RuleContext. The context carries the artifact-in-progress, the blocks list,
and the accumulator arrays (applied_rules, warnings, rule_faults).

A rule MAY mutate ctx.blocks, ctx.applied_rules, ctx.warnings. It MUST NOT
mutate ctx.rule_faults directly; the pipeline wraps rules in a fault
handler that populates rule_faults per I-7 automatically.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Protocol


@dataclass
class RuleContext:
    """State threaded through the rule pipeline.

    Attributes:
        blocks: CIR blocks, mutated in place as rules fire.
        applied_rules: L1b and L5 rule provenance (I-9).
        warnings: L3 validator output (I-9).
        rule_faults: L_any rule exceptions (I-7). Populated by the pipeline.
        manuscript_meta: Optional {title, subtitle, author} populated by
            C-003 from the title-page cluster. Any field may be None.
            Surfaces at the artifact top level via emit.build_artifact.
            Intake-vs-manuscript reconciliation (v1.1 punchlist) reads
            from here on the extraction side.
        intake_metadata: Optional {title, subtitle, author, ...} passed
            in by the caller (pronto_worker_1.py) from the Airtable
            Service record. Read by H-001 to decide between author's
            title page and system-generated. Rules MUST NOT write here.
        artifact: Top-level artifact under construction. Includes source,
            processing, version fields. Rules may read but typically don't
            mutate.
        extras: Per-rule scratch. Rules that need a small amount of shared
            state between phases (e.g., classifier state) can stash it here.
    """
    blocks: List[Dict[str, Any]]
    applied_rules: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)
    rule_faults: List[Dict[str, Any]] = field(default_factory=list)
    manuscript_meta: Optional[Dict[str, Any]] = None
    intake_metadata: Optional[Dict[str, Any]] = None
    artifact: Dict[str, Any] = field(default_factory=dict)
    extras: Dict[str, Any] = field(default_factory=dict)


class Rule(Protocol):
    """Every rule exposes these four attributes plus a run method.

    Conventions:
        id          — Doc 22 rule id, e.g., "N-001", "C-003", "V-004".
        phase       — One of ingest|strip|classify|normalize|validate|emit.
        order       — Integer, unique per phase.
        version     — Rule version, e.g., "v1". Included in applied_rules[]
                      and rule_faults[] entries for provenance.
    """
    id: str
    phase: str
    order: int
    version: str

    def run(self, ctx: RuleContext) -> None: ...


PHASES = ("ingest", "strip", "classify", "normalize", "validate", "emit")
