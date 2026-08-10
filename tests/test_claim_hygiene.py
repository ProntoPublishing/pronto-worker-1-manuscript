"""
Claim-time stale-state hygiene (sanctioned 2026-08-10).

A claim supersedes the previous run, so the previous run's verdict must
not survive underneath it. `Blocked` additionally feeds the Blocked
Services rollup that the delivery views read, so staleness there can
hold an order rather than merely mislead a reader.

Constructed with __new__ so the contract is tested without standing up
the worker's real clients or environment.
"""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pronto_worker_1 import ManuscriptProcessor  # noqa: E402


class TestClaimClearsStaleState(unittest.TestCase):
    def _written_fields(self):
        p = ManuscriptProcessor.__new__(ManuscriptProcessor)
        p.services_table = MagicMock()
        p.worker_version = "test"
        p._claim_service("svcTest")
        call = p.services_table.update.call_args
        return call.args[1]

    def test_claim_clears_error_log(self):
        self.assertEqual(self._written_fields()["Error Log"], "")

    def test_claim_clears_blocked_checkbox(self):
        self.assertIs(self._written_fields()["Blocked"], False)

    def test_claim_clears_blocked_reason(self):
        self.assertEqual(self._written_fields()["Blocked Reason"], "")

    def test_claim_still_sets_processing(self):
        f = self._written_fields()
        self.assertEqual(f["Status"], "Processing")
        self.assertIn("Started At", f)


class TestVoidIsTerminal(unittest.TestCase):
    """Void joins the terminal set (sanctioned 2026-08-10). W1's guard is
    inline in process_service, so it is exercised there rather than via
    check_idempotency."""

    def test_void_service_is_a_noop(self):
        p = ManuscriptProcessor.__new__(ManuscriptProcessor)
        p.services_table = MagicMock()
        p.services_table.get.return_value = {"fields": {"Status": "Void"}}
        out = p.process_service("svcTest")
        self.assertEqual(out["status"], "voided")
        p.services_table.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
