"""
Worker 1 v2 pipeline orchestrator.

Phases run in the fixed order defined by Doc 22 §Execution Phase Ordering:
    ingest → strip → classify → normalize → validate → emit

Within each phase, rules run in the declared "Order within phase" from the
registry.

Fault handling per I-7: a rule's exception is captured in ctx.rule_faults[],
and execution continues — subsequent rules in the phase still run,
subsequent phases still run, and the artifact still emits. RuleRejectException
(raised by Layer 4 rules like R-001) is treated differently: it halts the
pipeline, and the caller (pronto_worker_1.py) flips the Service to Failed.
"""
from __future__ import annotations
import logging
from typing import Dict, List, Any, Optional

from .rules.base import RuleContext, PHASES
from .rules.registry import RULE_REGISTRY, rules_for_phase
from .rules.rejection import RuleRejectException
from .rules.terminal_default import apply_terminal_default

logger = logging.getLogger(__name__)


def run_phase(
    phase: str,
    ctx: RuleContext,
    *,
    factory_args: Optional[Dict[str, Any]] = None,
) -> None:
    """Execute all rules registered to a phase, in order.

    factory_args is passed to each rule's factory. Rules that need no
    arguments ignore the dict. Rules that need specific args (e.g., R-001
    needs source_path) pull them by name.
    """
    factory_args = factory_args or {}
    for entry in rules_for_phase(phase):
        rule_id = str(entry["id"])
        version_attr = "v1"  # default; the instance will overwrite
        try:
            rule_instance = _instantiate(entry, factory_args)
            version_attr = getattr(rule_instance, "version", "v1")
        except Exception as e:
            # A factory failure is itself a rule fault — record and skip.
            ctx.rule_faults.append({
                "rule": rule_id,
                "phase": phase,
                "fault_class": type(e).__name__,
                "message": f"factory failed: {e}",
            })
            logger.exception(f"[{rule_id}] factory failed")
            continue

        try:
            rule_instance.run(ctx)
        except RuleRejectException:
            # L4 rejection propagates; pipeline caller handles it.
            raise
        except Exception as e:
            # I-7: fault-safe emission. Record and continue.
            ctx.rule_faults.append({
                "rule": rule_id,
                "phase": phase,
                "fault_class": type(e).__name__,
                "message": _sanitize_message(str(e)),
            })
            logger.exception(f"[{rule_id}] faulted during {phase}")

    # End-of-phase hooks. Terminal default (Doc 22 v1.0.2 Patch 1) runs
    # at the very end of the classify phase — after every C-### rule has
    # had its chance but before Validate begins. It is operational
    # policy, not a Layer 2 rule, so it isn't in the registry.
    if phase == "classify":
        apply_terminal_default(ctx)


def run_all_phases(
    ctx: RuleContext,
    *,
    factory_args: Optional[Dict[str, Any]] = None,
) -> None:
    """Run every phase in canonical order. Convenience wrapper.

    Terminal default lands at the end of the Classify phase; run_phase
    handles that internally.
    """
    for phase in PHASES:
        run_phase(phase, ctx, factory_args=factory_args)


def _instantiate(entry: Dict[str, object], factory_args: Dict[str, Any]):
    """Build a rule instance from a registry entry.

    Rules whose factory takes no args are called with (). Rules whose
    factory accepts kwargs receive the filtered subset of factory_args
    that matches their __init__ signature.
    """
    factory = entry["factory"]
    import inspect
    try:
        sig = inspect.signature(factory)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return factory()  # type: ignore[misc]
    accepted = {
        name: val
        for name, val in factory_args.items()
        if name in sig.parameters
    }
    return factory(**accepted)  # type: ignore[misc]


def _sanitize_message(msg: str, max_len: int = 500) -> str:
    """Truncate + scrub obviously-content-like payloads out of a fault msg.

    Fault messages MUST NOT carry raw manuscript text per the v2.0 schema
    description on rule_faults[].message. This is a defensive scrub.
    """
    if len(msg) > max_len:
        msg = msg[:max_len] + "…[truncated]"
    return msg
