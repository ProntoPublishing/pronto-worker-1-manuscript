# -*- coding: utf-8 -*-
"""Queue poller battery (order 9N2x9xK) — W1 flavor: no lib client,
the query rides the processor's Services table via app helper."""
import os
import unittest
from unittest.mock import MagicMock, patch


class TestQueuePoll(unittest.TestCase):
    def _app(self):
        with patch.dict(os.environ, {"QUEUE_POLL_ENABLED": "false"}):
            import app
        return app

    def test_formula(self):
        app = self._app()
        processor = MagicMock()
        processor.services_table.all.return_value = [
            {"id": "recX",
             "fields": {"Service Instance ID": "A-MANUSCRIPT"}}]
        ready = app._list_ready_services(processor)
        self.assertEqual(
            ready, [("recX", {"Service Instance ID": "A-MANUSCRIPT"})])
        formula = (processor.services_table.all.call_args.kwargs.get(
            "formula") or processor.services_table.all.call_args.args[0])
        self.assertIn("{Status}='Paid'", formula)
        self.assertIn("{Met}=1", formula)
        self.assertIn("-MANUSCRIPT", formula)

    def test_formula_failure_returns_empty(self):
        app = self._app()
        processor = MagicMock()
        processor.services_table.all.side_effect = RuntimeError("down")
        self.assertEqual(app._list_ready_services(processor), [])

    def test_arm_state_default(self):
        app = self._app()
        # W1 ships DISARMED: stale Paid+Met MANUSCRIPT backlog at
        # conversion time (8Najakz). Env flip arms it.
        self.assertEqual(app.QUEUE_POLL_DEFAULT, 'false')
        with patch.dict(os.environ, {"QUEUE_POLL_ENABLED": "TRUE"}):
            self.assertTrue(app._queue_poll_enabled())
        with patch.dict(os.environ, {"QUEUE_POLL_ENABLED": "yes"}):
            self.assertFalse(app._queue_poll_enabled())


if __name__ == "__main__":
    unittest.main()
