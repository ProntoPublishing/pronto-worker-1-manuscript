"""
Pronto Worker 1 — rule implementations.

Rules are organized by layer (N, C, V, R, H) in separate modules. The
registry module enumerates rules, their phase, and their order-within-phase.
Each rule implements the Rule protocol in `base.py`.

Specs-lead-code: every rule in this package traces 1:1 to a rule entry in
Doc 22 v1.0.1. If code and doc diverge, the doc is correct.
"""
from .registry import (
    RULE_REGISTRY,
    rules_for_phase,
    all_rule_ids,
)

__all__ = ["RULE_REGISTRY", "rules_for_phase", "all_rule_ids"]
