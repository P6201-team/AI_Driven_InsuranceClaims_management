from __future__ import annotations

import argparse
import json
from datetime import date

from tools import (
    check_duplicate_claim,
    check_line_coverage,
    check_narrative_risk,
    check_required_documents,
    find_preauthorisation,
    get_claim,
    issue_decision_letter,
    lookup_hospital,
    lookup_policy,
)


def pretty(title: str, payload) -> None:
    print(f"\n=== {title} ===")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def build_decision(claim, policy_lookup, duplicate_result, narrative_risk, line_results):
    policy = policy_lookup["policy"]
    remaining = policy_lookup["remaining"]
    service_date = claim["date_of_service"]
    total_amount = sum(line["amount"] for line in claim["lines"])

    if duplicate_result["is_duplicate"]:
        return {
            "decision": "escalate",
            "trigger": "duplicate_claim",
            "missing": None,
        }

    if narrative_risk["risk_detected"]:
        return {
            "decision": "escalate",
            "trigger": f"narrative_{narrative_risk['risk_type']}",
            "missing": None,
        }

    if policy["status"] != "active":
        return {
            "decision": "escalate",
            "trigger": "policy_lapsed",
            "missing": None,
        }

    if not (policy["start_date"] <= service_date <= policy["end_date"]):
        return {
            "decision": "escalate",
            "trigger": "outside_policy_dates",
            "missing": None,
        }

    if total_amount > remaining:
        return {
            "decision": "escalate",
            "trigger": "annual_limit_exceeded",
            "missing": None,
        }

    missing_documents = []
    for line in line_results:
        missing_documents.extend(line["documents"]["missing_documents"])
        if line["preauth"] is not None and line["preauth"]["status"] != "valid":
            missing_documents.append(f"preauth:{line['code']}")

    if missing_documents:
        return {
            "decision": "request_document",
            "trigger": None,
            "missing": sorted(set(missing_documents)),
        }

    return {
        "decision": "approve_in_principle",
        "trigger": None,
        "missing": None,
    }


def run_demo(claim_id: str) -> None:
    print("Problem A tools demo")
    print(f"claim_id = {claim_id}")
    print(f"run_date = {date.today().isoformat()}")

    claim = get_claim(claim_id)
    if claim is None:
        raise SystemExit(f"Claim not found: {claim_id}")
    pretty("1. get_claim", claim)

    policy_lookup = lookup_policy(claim["member_id"])
    if policy_lookup is None:
        raise SystemExit(f"Member or policy not found for member_id={claim['member_id']}")
    pretty("2. lookup_policy", policy_lookup)

    hospital = lookup_hospital(claim["hospital_id"])
    if hospital is None:
        raise SystemExit(f"Hospital not found: {claim['hospital_id']}")
    pretty("3. lookup_hospital", hospital)

    duplicate_result = check_duplicate_claim(
        claim["member_id"],
        claim["hospital_id"],
        claim["date_of_service"],
        claim["lines"],
    )
    pretty("4. check_duplicate_claim", duplicate_result)

    narrative_risk = check_narrative_risk(claim["narrative"])
    pretty("5. check_narrative_risk", narrative_risk)

    line_results = []
    for index, line in enumerate(claim["lines"], start=1):
        coverage = check_line_coverage(line["code"], policy_lookup["policy"]["policy_id"])
        if coverage is None:
            raise SystemExit(f"Coverage lookup failed for code={line['code']}")

        line_result = {
            "line_number": index,
            "code": line["code"],
            "amount": line["amount"],
            "coverage": coverage,
            "preauth": None,
            "documents": check_required_documents(line["code"], claim["documents"]),
        }

        if coverage["requires_preauth"]:
            line_result["preauth"] = find_preauthorisation(
                claim["member_id"],
                line["code"],
                claim["date_of_service"],
            )

        line_results.append(line_result)
        pretty(f"6.{index} line analysis", line_result)

    decision_draft = build_decision(
        claim,
        policy_lookup,
        duplicate_result,
        narrative_risk,
        line_results,
    )
    pretty("7. decision draft", decision_draft)

    approved_total = sum(
        line["amount"]
        for line, result in zip(claim["lines"], line_results)
        if not result["coverage"]["excluded"]
    )
    refused_total = sum(
        line["amount"]
        for line, result in zip(claim["lines"], line_results)
        if result["coverage"]["excluded"]
    )

    receipt = issue_decision_letter(
        claim_id=claim["claim_id"],
        decision=decision_draft["decision"],
        lines_resolved=len(claim["lines"]),
        approved_total=approved_total,
        refused_total=refused_total,
        trigger=decision_draft["trigger"],
        missing=decision_draft["missing"],
    )
    pretty("8. issue_decision_letter", receipt)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a simple Problem A tool demo.")
    parser.add_argument(
        "--claim-id",
        default="CLM-8842",
        help="Claim id to run. Default: CLM-8842",
    )
    args = parser.parse_args()
    run_demo(args.claim_id)


if __name__ == "__main__":
    main()
