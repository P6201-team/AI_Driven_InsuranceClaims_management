
import json
from typing import Literal, List, Dict, Any


# ============================================================
# CLAIM LOOKUP
# ============================================================

def get_claim(claim_id: str) -> Dict[str, Any]:
    """
    NAME/SIGNATURE: get_claim(claim_id: str) -> dict

    WHAT:
        Retrieves the complete claim record.

    RETURNS:
        member_id
        hospital_id
        date_of_service
        lines
    """

    if claim_id == "CLM-8842":
        return {
            "claim_id": "CLM-8842",
            "member_id": "M-2214",
            "hospital_id": "H-114",
            "date_of_service": "2026-05-14",

            "lines": [
                {
                    "code": "47120",
                    "amount": 1400
                },
                {
                    "code": "62480",
                    "amount": 780
                },
                {
                    "code": "31255",
                    "amount": 500
                }
            ]
        }

    return {
        "error": "Claim not found"
    }


# ============================================================
# POLICY LOOKUP
# ============================================================

def lookup_policy(member_id: str) -> Dict[str, Any]:
    """
    NAME/SIGNATURE: lookup_policy(member_id: str) -> dict

    WHAT:
        Retrieves the policy associated with the member.

    IMPORTANT:
        remaining = annual_limit - used_to_date
    """

    if member_id == "M-2214":

        annual_limit = 10000
        used_to_date = 3000
        remaining = annual_limit - used_to_date

        return {
            "policy": {
                "policy_id": "POL-3310",
                "product": "Gold Plus",
                "status": "active",
                "start_date": "2026-01-01",
                "end_date": "2026-12-31",
                "annual_limit": annual_limit,
                "used_to_date": used_to_date,
                "exclusions": [
                    "EX-14"
                ]
            },
            "remaining": remaining
        }

    return {
        "error": "Policy not found"
    }


# ============================================================
# HOSPITAL LOOKUP
# ============================================================

def lookup_hospital(hospital_id: str) -> Dict[str, Any]:
    """
    NAME/SIGNATURE: lookup_hospital(hospital_id: str) -> dict

    WHAT:
        Retrieves hospital panel/network information.
    """

    if hospital_id == "H-114":

        return {
            "hospital_id": "H-114",
            "name": "Example Hospital",
            "panel_status": "in_network"
        }

    return {
        "error": "Hospital not found"
    }


# ============================================================
# COVERAGE CHECK
# ============================================================

def check_coverage(
    procedure_code: str,
    policy_id: str
) -> Dict[str, Any]:
    """
    NAME/SIGNATURE:
        check_coverage(procedure_code: str, policy_id: str) -> dict

    WHAT:
        Returns all coverage information required by the agent.

    OUTPUT FIELDS:
        code
        description
        requires_preauth
        excluded
        exclusion_rule
    """

    coverage_table = {

        "47120": {
            "code": "47120",
            "description": "Procedure 47120",
            "requires_preauth": False,
            "excluded": False,
            "exclusion_rule": None
        },

        "62480": {
            "code": "62480",
            "description": "Procedure 62480",
            "requires_preauth": True,
            "excluded": False,
            "exclusion_rule": None
        },

        "31255": {
            "code": "31255",
            "description": "Procedure 31255",
            "requires_preauth": False,
            "excluded": True,
            "exclusion_rule": "EX-14"
        }
    }

    if procedure_code not in coverage_table:
        return {
            "code": procedure_code,
            "description": "Unknown procedure",
            "requires_preauth": False,
            "excluded": True,
            "exclusion_rule": "UNKNOWN_PROCEDURE"
        }

    return coverage_table[procedure_code]


# ============================================================
# PRE-AUTHORIZATION
# ============================================================

def get_preauthorisation(
    member_id: str,
    procedure_code: str
) -> Dict[str, Any]:
    """
    NAME/SIGNATURE:
        get_preauthorisation(member_id: str, procedure_code: str) -> dict

    WHAT:
        Checks whether a valid pre-authorisation exists.
    """

    # Problem A reference:
    # 62480 is the line that requires pre-authorisation.

    if (
        member_id == "M-2214"
        and procedure_code == "62480"
    ):
        return {
            "procedure_code": "62480",
            "preauth_found": True,
            "reference": "PA-62480-2214"
        }

    return {
        "procedure_code": procedure_code,
        "preauth_found": False,
        "message": (
            f"No valid pre-authorization on file for "
            f"{procedure_code}"
        )
    }


# ============================================================
# FINAL DECISION
# ============================================================

def issue_decision_letter(
    case_id: str,
    decision: Literal[
        "approve_in_principle",
        "request_document",
        "escalate"
    ],
    reason: str,
    evidence: List[str]
) -> str:
    """
    NAME/SIGNATURE:
        issue_decision_letter(...) -> str

    WHAT:
        Final autonomous decision.

    IMPORTANT:
        This function records the decision.
        It does NOT contain case-specific business rules.

        The agent is responsible for ensuring all required
        checks have been completed before calling this tool.
    """

    if decision not in {
        "approve_in_principle",
        "request_document",
        "escalate"
    }:
        raise ValueError(
            f"Invalid decision: {decision}"
        )

    log_entry = {
        "case_id": case_id,
        "decision": decision,
        "reason": reason,
        "evidence": evidence,
        "autonomy": "autonomous"
    }

    with open(
        f"{case_id}_decision_log.json",
        "w"
    ) as f:

        json.dump(
            log_entry,
            f,
            indent=4
        )

    return (
        f"Decision '{decision}' successfully "
        f"logged for {case_id}."
    )

