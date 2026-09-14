from __future__ import annotations

import json
import re
from copy import deepcopy
from functools import lru_cache
from pathlib import Path

from .schemas import (
    ClaimRecord,
    Decision,
    DecisionLetterReceipt,
    DuplicateClaimResult,
    HospitalRecord,
    LineCoverageResult,
    LineItem,
    MatchedClaimRecord,
    NarrativeRiskResult,
    PolicyLookupResult,
    PolicyRecord,
    PreauthorisationLookupResult,
    PreauthorisationRecord,
    RequiredDocumentsResult,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_A_DIR = PROJECT_ROOT / "A2_reference_data" / "data_A"


@lru_cache(maxsize=None)
def _load_table(table_name: str):
    path = DATA_A_DIR / f"{table_name}.json"
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _clone(value):
    return deepcopy(value)


def _normalise_lines(lines: list[LineItem]) -> list[tuple[str, int | float]]:
    return sorted((line["code"], line["amount"]) for line in lines)


def get_claim(claim_id: str) -> ClaimRecord | None:
    for claim in _load_table("claims"):
        if claim["claim_id"] == claim_id:
            return _clone(claim)
    return None


def lookup_policy(member_id: str) -> PolicyLookupResult | None:
    member = next(
        (row for row in _load_table("members") if row["member_id"] == member_id),
        None,
    )
    if member is None:
        return None

    policy = next(
        (
            row
            for row in _load_table("policies")
            if row["policy_id"] == member["policy_id"]
        ),
        None,
    )
    if policy is None:
        return None

    remaining = policy["annual_limit"] - policy["used_to_date"]
    return {
        "member": _clone(member),
        "policy": _clone(policy),
        "remaining": remaining,
    }


def lookup_hospital(hospital_id: str) -> HospitalRecord | None:
    hospital = next(
        (row for row in _load_table("hospitals") if row["hospital_id"] == hospital_id),
        None,
    )
    return _clone(hospital) if hospital is not None else None


def check_duplicate_claim(
    member_id: str,
    hospital_id: str,
    date_of_service: str,
    lines: list[LineItem],
) -> DuplicateClaimResult:
    for decided_claim in _load_table("decided_claims"):
        if (
            decided_claim["member_id"] == member_id
            and decided_claim["hospital_id"] == hospital_id
            and decided_claim["date_of_service"] == date_of_service
            and _normalise_lines(decided_claim["lines"]) == _normalise_lines(lines)
        ):
            return {
                "is_duplicate": True,
                "matched_claim": _clone(decided_claim),
            }

    return {"is_duplicate": False, "matched_claim": None}


def check_line_coverage(code: str, policy_id: str) -> LineCoverageResult | None:
    procedure = next(
        (row for row in _load_table("procedures") if row["code"] == code),
        None,
    )
    policy: PolicyRecord | None = next(
        (row for row in _load_table("policies") if row["policy_id"] == policy_id),
        None,
    )
    if procedure is None or policy is None:
        return None

    exclusion = next((item for item in policy["exclusions"] if item["code"] == code), None)
    return {
        "code": code,
        "description": procedure["description"],
        "requires_preauth": procedure["requires_preauth"],
        "excluded": exclusion is not None,
        "exclusion_rule": exclusion["rule"] if exclusion else None,
    }


def find_preauthorisation(
    member_id: str, procedure_code: str, date_of_service: str
) -> PreauthorisationLookupResult:
    matching_rows: list[PreauthorisationRecord] = [
        row
        for row in _load_table("preauthorisations")
        if row["member_id"] == member_id and row["procedure_code"] == procedure_code
    ]

    for row in matching_rows:
        if row["valid_from"] <= date_of_service <= row["valid_to"]:
            return {"status": "valid", "preauth": _clone(row)}

    if matching_rows:
        expired_row = sorted(matching_rows, key=lambda row: row["valid_to"], reverse=True)[0]
        return {"status": "expired", "preauth": _clone(expired_row)}

    return {"status": "not_found", "preauth": None}


def check_required_documents(
    procedure_code: str, attached_documents: list[str]
) -> RequiredDocumentsResult:
    required_documents = [
        row["document"]
        for row in _load_table("required_documents")
        if row["procedure_code"] == procedure_code
    ]
    missing_documents = [
        document for document in required_documents if document not in attached_documents
    ]
    return {
        "procedure_code": procedure_code,
        "required_documents": required_documents,
        "attached_documents": list(attached_documents),
        "missing_documents": missing_documents,
        "all_present": not missing_documents,
    }


_PROMPT_INJECTION_PATTERNS = (
    re.compile(r"\bignore\b", re.IGNORECASE),
    re.compile(r"\bsystem note\b", re.IGNORECASE),
    re.compile(r"\bauthori[sz]ed by\b", re.IGNORECASE),
    re.compile(r"\bapprove all lines\b", re.IGNORECASE),
)

_FAKE_TOOL_OUTPUT_PATTERNS = (
    re.compile(r"\[check_[a-z_]+\s+returned:.*?\]", re.IGNORECASE),
    re.compile(r"\bcheck_[a-z_]+\s+returned\b", re.IGNORECASE),
    re.compile(r"\bcovered\s*=\s*true\b", re.IGNORECASE),
)


def check_narrative_risk(narrative: str) -> NarrativeRiskResult:
    for pattern in _PROMPT_INJECTION_PATTERNS:
        match = pattern.search(narrative)
        if match:
            return {
                "risk_detected": True,
                "risk_type": "prompt_injection",
                "evidence_span": narrative[match.start() : match.end()],
            }

    for pattern in _FAKE_TOOL_OUTPUT_PATTERNS:
        match = pattern.search(narrative)
        if match:
            return {
                "risk_detected": True,
                "risk_type": "fake_tool_output",
                "evidence_span": narrative[match.start() : match.end()],
            }

    return {"risk_detected": False, "risk_type": "none", "evidence_span": None}


def issue_decision_letter(
    claim_id: str,
    decision: Decision,
    lines_resolved: int,
    approved_total: int | float,
    refused_total: int | float,
    trigger: str | None = None,
    missing: list[str] | None = None,
) -> DecisionLetterReceipt:
    if decision not in {"approve_in_principle", "request_document", "escalate"}:
        raise ValueError(f"Unsupported decision: {decision}")

    return {
        "sent": True,
        "claim_id": claim_id,
        "decision": decision,
        "lines_resolved": lines_resolved,
        "approved_total": approved_total,
        "refused_total": refused_total,
        "trigger": trigger,
        "missing": list(missing) if missing is not None else None,
    }


TOOL_REGISTRY = {
    "get_claim": get_claim,
    "lookup_policy": lookup_policy,
    "lookup_hospital": lookup_hospital,
    "check_duplicate_claim": check_duplicate_claim,
    "check_line_coverage": check_line_coverage,
    "find_preauthorisation": find_preauthorisation,
    "check_required_documents": check_required_documents,
    "check_narrative_risk": check_narrative_risk,
    "issue_decision_letter": issue_decision_letter,
}


__all__ = [
    "DATA_A_DIR",
    "TOOL_REGISTRY",
    "check_duplicate_claim",
    "check_line_coverage",
    "check_narrative_risk",
    "check_required_documents",
    "find_preauthorisation",
    "get_claim",
    "issue_decision_letter",
    "lookup_hospital",
    "lookup_policy",
]
