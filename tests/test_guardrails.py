"""Regression tests for the D3(b) scaffold-integrated checklist."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import agent
import backends
import config
import tools
from tests.guardrail_runner import load_cases, run_checklist, run_case


class GuardrailChecklistTests(unittest.TestCase):
    def test_checklist_shape(self):
        cases = load_cases()
        self.assertGreaterEqual(len(cases), 10)
        self.assertGreaterEqual(
            sum(case["hostile_request_text"] for case in cases), 3
        )
        self.assertEqual(
            len({case["case_id"] for case in cases}), len(cases)
        )
        for case in cases:
            with self.subTest(case_id=case["case_id"]):
                self.assertTrue(case["wrong_behaviour_to_catch"].strip())
                self.assertIn("expected", case)
                self.assertIn("script", case)

    def test_every_scripted_guardrail_case_passes(self):
        summary = run_checklist()
        self.assertEqual(summary["failed"], 0)

    def test_gated_action_log_is_structured(self):
        case = next(c for c in load_cases() if c["case_id"] == "GR-04")
        result = run_case(case)
        self.assertTrue(result["passed"], result["mismatches"])
        self.assertEqual(len(result["decision_log"]), 1)
        logged = result["decision_log"][0]
        for field in (
            "timestamp_utc",
            "case_id",
            "action",
            "payload",
            "evidence",
            "result",
            "autonomy",
            "gate",
        ):
            self.assertIn(field, logged)
        self.assertEqual(logged["action"], "issue_decision_letter")
        self.assertEqual(logged["autonomy"], "act")
        self.assertEqual(logged["evidence"], ["get_claim"])
        self.assertEqual(logged["gate"]["guardrail"], "gate_passed")

    def test_live_confirm_mode_does_not_auto_approve(self):
        class FakeLiveBackend:
            name = "live"

            def next_move(self, transcript):
                return {
                    "thought": "Attempt an irreversible action.",
                    "calls": [["issue_decision_letter", {
                        "claim_id": "GR-LIVE",
                        "decision": "escalate",
                        "lines_resolved": 0,
                        "approved_total": 0,
                        "refused_total": 0,
                    }]],
                }

            def token_estimate(self, transcript):
                return 10, 5

        old = (config.AUTONOMY, config.MAX_TURNS, config.MAX_TOKENS_PER_RUN)
        original_action = tools.REGISTRY["A"]["issue_decision_letter"]
        try:
            config.AUTONOMY = "confirm"
            config.MAX_TURNS = 2
            config.MAX_TOKENS_PER_RUN = 1000
            tools.REGISTRY["A"]["issue_decision_letter"] = lambda **kw: {
                "sent": True, **kw
            }
            with tempfile.TemporaryDirectory() as tmp, patch.object(
                agent, "make_backend", return_value=FakeLiveBackend()
            ):
                log_path = Path(tmp) / "decision_log.jsonl"
                record = agent.run_case(
                    "GR-LIVE", problem="A", decision_log_path=log_path
                )
                self.assertEqual(record["stopped_by"], "gate_held")
                self.assertFalse(log_path.exists())
        finally:
            config.AUTONOMY, config.MAX_TURNS, config.MAX_TOKENS_PER_RUN = old
            tools.REGISTRY["A"]["issue_decision_letter"] = original_action

    def test_live_backend_exposes_measured_usage(self):
        backend = backends.LiveBackend("GR-USAGE", [], "system")
        response = '{"final":{"decision":"escalate","reason":"test"}}'
        with patch.object(backends, "_live_call", return_value=(response, (123, 45))):
            backend.next_move([])
        self.assertEqual(backend.token_estimate([]), (123, 45))


if __name__ == "__main__":
    unittest.main()
