"""
Layer 4 rejection rules.

Per Doc 22 §Layer 4: Fail loud and early. Worker 1 halts; Service flips to
Failed with an actionable Error Log note.
"""
from __future__ import annotations
from pathlib import Path
from typing import Any

from .base import RuleContext


class RuleRejectException(Exception):
    """Raised by an R-### rule to signal ingest-time rejection. The
    pipeline catches this and halts — a rejection is not a rule fault."""

    def __init__(self, rule_id: str, message: str) -> None:
        super().__init__(message)
        self.rule_id = rule_id
        self.message = message


class R001_UnsupportedFormat:
    """R-001: v1 Worker 1 accepts .docx only. Receives anything else → reject.

    Implementation notes (Doc 22 R-001 v1):
      - Runs first within the ingest phase (order=1), before N-002 and
        before extraction, per Execution Phase Ordering.
      - Decides purely on extension; content-sniffing is out of scope.
        A .docx file with a different MIME type is still accepted; a
        .pdf file with a DOCX payload is still rejected.
    """

    id = "R-001"
    phase = "ingest"
    order = 1
    version = "v1"

    def __init__(self, source_path: str | Path) -> None:
        self._path = Path(source_path)

    def run(self, ctx: RuleContext) -> None:
        ext = self._path.suffix.lower().lstrip(".")
        if ext == "docx":
            return  # accepted, fall through to extraction
        raise RuleRejectException(
            rule_id=self.id,
            message=(
                f"v1 Worker 1 accepts .docx only. "
                f"Received: {ext or '<no extension>'}."
            ),
        )
