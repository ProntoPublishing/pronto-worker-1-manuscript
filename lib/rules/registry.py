"""
Rule registry — lists every rule in Doc 22 v1.0.1 with its phase + order.

In iteration 1 only R-001 is wired. Subsequent iterations fill in the rest;
the registry's shape is intended to be stable across iterations so the
pipeline orchestrator doesn't need changes when rules are added.

The registry is a list of descriptors (rule_id, phase, order, factory).
The `factory` is a callable that returns a rule instance. Rules that need
construction context (e.g., R-001 needs the source path) take it via the
factory's closure at pipeline setup.
"""
from __future__ import annotations
from typing import Callable, Dict, List

from .base import Rule
from .rejection import R001_UnsupportedFormat
from .normalization import (
    N001_CollapseDoubleSpaces,
    N003_StripZeroWidthAndLayoutHacks,
    N004_QuoteNormalization,
    N005_StripLicenseBoilerplate,
)
from .classification import (
    C001_LandmarkClassification,
    C002_StructuralPartDetection,
    C003_TitlePage,
    C004_FrontMatter,
    C005_BackMatter,
    C006_ChapterSubtitle,
    C007_SourceTocDetection,
    C008_PatternOnlyLandmarks,
)
from .validation import (
    V001_ChapterNumberContinuity,
    V002_HeadingStyleConsistency,
    V003_SpaceLossHeuristic,
    V004_TrackedChangesResidueDetector,
    V005_ZeroStructure,
    V006_PatternOnlyPromotion,
)
from .human import H001_AuthorTitlePageVsIntake


RuleFactory = Callable[..., Rule]


# Each entry: (rule_id, phase, order, factory). Subsequent iterations add
# entries here alongside their implementations.
#
# Phase ordering within each phase is authoritative here — matches the
# "Order within phase" field on every rule entry in Doc 22 v1.0.1.
RULE_REGISTRY: List[Dict[str, object]] = [
    {"id": "R-001", "phase": "ingest",   "order": 1, "factory": R001_UnsupportedFormat},
    # N-002 (ingest, order 2) — implemented in the DOCX extractor itself
    # (tracked-change acceptance happens during DOCX → CIR). No pluggable
    # rule entry in the registry; V-004 catches leaks.

    {"id": "N-001", "phase": "strip",     "order": 1, "factory": N001_CollapseDoubleSpaces},
    {"id": "N-003", "phase": "strip",     "order": 2, "factory": N003_StripZeroWidthAndLayoutHacks},
    {"id": "N-005", "phase": "strip",     "order": 3, "factory": N005_StripLicenseBoilerplate},

    # Rules 1.2 (Gate 2 rulings Q1/Q3, 2026-07-16): C-007 runs FIRST so
    # source-TOC blocks are off the table before stratum analysis;
    # C-008 runs after C-001 (needs its strata analysis and fires only
    # when the visual-gate path found nothing) and before front/back
    # matter (which need landmark cutoffs). Orders renumbered — Doc 22
    # v1.2 drafting must update the "Order within phase" fields.
    {"id": "C-007", "phase": "classify",  "order": 1, "factory": C007_SourceTocDetection},
    {"id": "C-001", "phase": "classify",  "order": 2, "factory": C001_LandmarkClassification},
    {"id": "C-008", "phase": "classify",  "order": 3, "factory": C008_PatternOnlyLandmarks},
    {"id": "C-002", "phase": "classify",  "order": 4, "factory": C002_StructuralPartDetection},
    {"id": "C-006", "phase": "classify",  "order": 5, "factory": C006_ChapterSubtitle},
    {"id": "C-004", "phase": "classify",  "order": 6, "factory": C004_FrontMatter},
    {"id": "C-005", "phase": "classify",  "order": 7, "factory": C005_BackMatter},
    {"id": "C-003", "phase": "classify",  "order": 8, "factory": C003_TitlePage},

    {"id": "N-004", "phase": "normalize", "order": 1, "factory": N004_QuoteNormalization},

    {"id": "V-001", "phase": "validate",  "order": 1, "factory": V001_ChapterNumberContinuity},
    {"id": "V-002", "phase": "validate",  "order": 2, "factory": V002_HeadingStyleConsistency},
    {"id": "V-003", "phase": "validate",  "order": 3, "factory": V003_SpaceLossHeuristic},
    {"id": "V-004", "phase": "validate",  "order": 4, "factory": V004_TrackedChangesResidueDetector},
    {"id": "V-005", "phase": "validate",  "order": 5, "factory": V005_ZeroStructure},
    {"id": "V-006", "phase": "validate",  "order": 6, "factory": V006_PatternOnlyPromotion},

    {"id": "H-001", "phase": "emit",      "order": 1, "factory": H001_AuthorTitlePageVsIntake},
]


def rules_for_phase(phase: str) -> List[Dict[str, object]]:
    """Return registry entries for a phase, sorted by order."""
    entries = [e for e in RULE_REGISTRY if e["phase"] == phase]
    entries.sort(key=lambda e: e["order"])
    return entries


def all_rule_ids() -> List[str]:
    return [str(e["id"]) for e in RULE_REGISTRY]
