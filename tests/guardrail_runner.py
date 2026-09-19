"""Run the D3(b) checklist through the active scaffold runtime."""
import json
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import agent
import backends
import config
import tools


HERE = Path(__file__).resolve().parent
CASE_PATH = HERE / "guardrail_cases.json"


def load_cases():
    with CASE_PATH.open(encoding="utf-8") as stream:
        return json.load(stream)


def _stub(name):
    def call(**arguments):
        if name == "get_claim":
            return {
                "claim_id": arguments.get("claim_id"),
                "member_id": "M-GR",
                "hospital_id": "H-GR",
                "date_of_service": "2026-09-02",
                "narrative": "",
                "documents": [],
                "lines": [{"code": "47120", "amount": 100}],
            }
        if name == "issue_decision_letter":
            return {"sent": True, **arguments}
        return {"ok": True, "tool": name, "arguments": arguments}
    return call


@contextmanager
def _active_scripted_case(case):
    names = ("BACKEND", "MAX_TURNS", "MAX_TOKENS_PER_RUN", "AUTONOMY")
    old_config = {name: getattr(config, name) for name in names}
    registry = tools.REGISTRY["A"]
    old_registry = dict(registry)
    had_script = case["case_id"] in backends.SCRIPTS
    old_script = backends.SCRIPTS.get(case["case_id"])
    try:
        config.BACKEND = "scripted"
        config.MAX_TURNS = case["config"]["max_turns"]
        config.MAX_TOKENS_PER_RUN = case["config"]["max_tokens"]
        config.AUTONOMY = case["config"]["autonomy"]
        backends.SCRIPTS[case["case_id"]] = case["script"]
        registry.update({name: _stub(name) for name in registry})
        yield
    finally:
        for name, value in old_config.items():
            setattr(config, name, value)
        registry.clear()
        registry.update(old_registry)
        if had_script:
            backends.SCRIPTS[case["case_id"]] = old_script
        else:
            backends.SCRIPTS.pop(case["case_id"], None)


def _observed_text(record, log_records):
    stopped = record.get("stopped_by")
    if stopped:
        return (
            "Stopped by %s before any prohibited follow-on action; "
            "%d tool action(s) executed and %d gated record(s) were written."
            % (stopped, len(record.get("evidence") or []), len(log_records))
        )
    return "No guardrail stop was observed."


def run_case(case):
    approval = case.get("operator_approval")
    approve = None if approval is None else (lambda action, payload: approval)

    with tempfile.TemporaryDirectory() as tmp, _active_scripted_case(case):
        log_path = Path(tmp) / "decision_log.jsonl"
        record = agent.run_case(
            case["case_id"],
            problem="A",
            approve=approve,
            request_text=case["request_text"],
            decision_log_path=log_path,
        )
        log_records = []
        if log_path.exists():
            log_records = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]

    observed = {
        "stopped_by": record.get("stopped_by"),
        "decision": record.get("decision"),
        "turns": record.get("turns"),
        "tokens_in": record.get("tokens_in"),
        "tokens_out": record.get("tokens_out"),
        "cost_usd": record.get("cost_usd"),
        "evidence_count": len(record.get("evidence") or []),
        "guardrails_fired": record.get("guardrails_fired") or [],
        "decision_log_records": len(log_records),
    }
    mismatches = [
        "%s=%r, expected %r" % (key, observed.get(key), expected)
        for key, expected in case["expected"].items()
        if observed.get(key) != expected
    ]
    return {
        "case_id": case["case_id"],
        "legacy_case_id": case.get("legacy_case_id"),
        "family": case["family"],
        "migration": case["migration"],
        "hostile_request_text": case["hostile_request_text"],
        "wrong_behaviour_to_catch": case["wrong_behaviour_to_catch"],
        "request_text": case["request_text"],
        "expected": case["expected"],
        "observed": observed,
        "observed_result": _observed_text(record, log_records),
        "decision_log": log_records,
        "passed": not mismatches,
        "mismatches": mismatches,
    }


def run_checklist(output_path=None, verbose=False):
    results = [run_case(case) for case in load_cases()]
    passed = sum(result["passed"] for result in results)
    hostile = sum(result["hostile_request_text"] for result in results)
    summary = {
        "cases": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "hostile_request_text_cases": hostile,
        "backend": "scripted",
    }
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "results": results,
    }
    if output_path:
        Path(output_path).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if verbose:
        print("D3(b) GUARDRAIL CHECKLIST — SCRIPTED BACKEND")
        for result in results:
            mark = "PASS" if result["passed"] else "FAIL"
            print("  %-5s %-6s %-38s %s" % (
                mark,
                result["case_id"],
                result["family"],
                result["observed_result"],
            ))
            for mismatch in result["mismatches"]:
                print("        %s" % mismatch)
        print(
            "  summary: %d/%d passed; %d hostile-request-text cases"
            % (passed, len(results), hostile)
        )
        if output_path:
            print("  wrote %s" % output_path)
    return summary


if __name__ == "__main__":
    run_checklist(output_path="guardrail_results.json", verbose=True)
