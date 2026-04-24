"""
Layer 5 human-clarification defaults — H-001 through H-###.

Per Doc 22 §Layer 5: ambiguous cases that should eventually ask the
author. The author-back-channel does not yet exist, so each rule applies
a documented default with a mandatory entry in applied_rules[] and,
when appropriate, a warning for human review.
"""
from __future__ import annotations
from typing import Dict, List, Any

from .base import RuleContext


def _norm(s: Any) -> str:
    """Case-insensitive, whitespace-trimmed normalization for comparison."""
    if s is None:
        return ""
    return str(s).strip().lower()


class H001_AuthorTitlePageVsIntake:
    """H-001 v1: Author-supplied title page vs intake metadata.

    Fires during the emit phase when BOTH of these are true:
      - C-003 produced a title_page cluster (ctx.manuscript_meta has a
        non-empty title).
      - The caller supplied intake metadata (ctx.intake_metadata has a
        non-empty title or author).

    Behavior per Doc 22 v1 H-001:
      - Records an applied_rules[] entry: {rule: "H-001", version: "v1",
        decision: "used author title page; suppressed system-generated"}.
        Downstream (W2) reads this entry — the decision tells the
        renderer not to auto-generate another title page.
      - Optional divergence warning: when the author's extracted title
        or author name differs materially from intake (case-insensitive,
        whitespace-trimmed), emit a warnings[] entry anchored to H-001
        so operators can spot possibly-wrong intake metadata.

    Cases that do NOT fire H-001:
      - C-003 did not find a title page (author didn't supply one) —
        W2 generates from intake; no conflict to resolve.
      - Intake has neither title nor author — no data to check against.
      - Both missing — the no-title-page path; W2's own defaults apply.
    """

    id = "H-001"
    phase = "emit"
    order = 1
    version = "v1"

    def run(self, ctx: RuleContext) -> None:
        ms = ctx.manuscript_meta or {}
        intake = ctx.intake_metadata or {}

        ms_title  = (ms.get("title")  or "").strip()
        ms_author = (ms.get("author") or "").strip()
        intake_title  = (intake.get("title")  or "").strip()
        intake_author = (intake.get("author") or "").strip()

        # Author must have supplied a title page (we have a manuscript
        # title extracted).
        if not ms_title:
            return
        # Intake must carry at least one field to compare against.
        if not (intake_title or intake_author):
            return

        ctx.applied_rules.append({
            "rule": "H-001",
            "version": "v1",
            "decision": "used author title page; suppressed system-generated",
        })

        # Optional divergence warning.
        diffs: List[str] = []
        if intake_title and ms_title and _norm(ms_title) != _norm(intake_title):
            diffs.append(
                f"title differs: manuscript={ms_title!r}, intake={intake_title!r}"
            )
        if intake_author and ms_author and _norm(ms_author) != _norm(intake_author):
            diffs.append(
                f"author differs: manuscript={ms_author!r}, intake={intake_author!r}"
            )

        if diffs:
            ctx.warnings.append({
                "rule": "H-001",
                "severity": "medium",
                "detail": "; ".join(diffs),
            })
