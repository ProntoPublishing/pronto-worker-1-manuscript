"""
Doc 08 secret-contract gate (retrofit 2026-07-19): 503 when the
server has no WEBHOOK_SECRET, 401 on missing or wrong header, and a
correct header passes through to normal request validation. W2 ran
1.0->1.7.3 without any check — Jesse found the empty Variables panel.
"""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app import app


class TestSecretGate(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_unconfigured_server_503(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = self.client.post("/process", json={"service_id": "x"})
        self.assertEqual(resp.status_code, 503)

    def test_missing_header_401(self):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cret"}):
            resp = self.client.post("/process", json={"service_id": "x"})
        self.assertEqual(resp.status_code, 401)

    def test_wrong_header_401(self):
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cret"}):
            resp = self.client.post("/process", json={"service_id": "x"},
                                    headers={"X-Webhook-Secret": "nope"})
        self.assertEqual(resp.status_code, 401)

    def test_correct_header_passes_gate(self):
        # Missing service_id -> 400 proves the gate let the request in.
        with patch.dict(os.environ, {"WEBHOOK_SECRET": "s3cret"}):
            resp = self.client.post("/process", json={},
                                    headers={"X-Webhook-Secret": "s3cret"})
        self.assertEqual(resp.status_code, 400)

    def test_health_needs_no_secret(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WEBHOOK_SECRET", None)
            resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
