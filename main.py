# main.py

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from tools import (
    get_claim,
    lookup_policy,
    lookup_hospital,
    check_duplicate_claim,
    check_line_coverage,
    find_preauthorisation,
    check_required_documents,
    check_narrative_risk,
    issue_decision_letter,
)


# ============================================================
# CONFIG
# ============================================================

MAX_TURNS = 8

# Keep the irreversible action behind an explicit gate.
AUTONOMY_MODE = "confirm"


# ============================================================
# HELPERS
# ============================================================

def get_value(obj, *keys, default=None):
    """
    Safely retrieve a value from a dict-like object.

    Allows the workflow to tolerate small naming differences
    in the existing TypedDict schemas.
    """
    if obj is None:
        return default

    for key in keys:
        if isinstance(obj, dict) and key in obj:
            return obj[key]

        if hasattr(obj, key):
            return getattr(obj, key)

    return default


def result_value(result):
    """
    Unwrap our run_tool result.
    """
    return result.get("result") if result.get("success") else None


# ============================================================
# EVIDENCE LEDGER
# ============================================================

@dataclass
class Evidence:
    turn: int
    tool: str
    result: Any


@dataclass
class EvidenceLedger:

    entries: list[Evidence] = field(default_factory=list)

    def add(self, turn: int, tool: str, result: Any):
        self.entries.append(
            Evidence(
                turn=turn,
                tool=tool,
                result=result,
            )
        )

    def export(self):
        return [
            {
                "turn": e.turn,
                "tool": e.tool,
                "result": e.result,
            }
            for e in self.entries
        ]


# ============================================================
# WORKFLOW CONTEXT
# ============================================================

@dataclass
class WorkflowContext:

    claim_id: str

    turn: int = 0

    claim: Any = None
    policy: Any = None
    hospital: Any = None
    duplicate: Any = None
    narrative_risk: Any = None

    coverage: dict = field(default_factory=dict)
    documents: dict = field(default_factory=dict)
    preauthorisations: dict = field(default_factory=dict)

    evidence: EvidenceLedger = field(
        default_factory=EvidenceLedger
    )

    tool_history: list = field(default_factory=list)

    decision: Any = None

    approved_total: float = 0
    refused_total: float = 0

    def next_turn(self):

        self.turn += 1

        if self.turn > MAX_TURNS:
            raise RuntimeError(
                f"Maximum turn limit ({MAX_TURNS}) exceeded."
            )

        print(
            f"\n{'=' * 18} TURN {self.turn} {'=' * 18}"
        )


# ============================================================
# SAFE TOOL EXECUTION
# ============================================================

async def run_tool(
    name: str,
    function,
    *args,
):

    try:

        result = await asyncio.to_thread(
            function,
            *args,
        )

        return {
            "tool": name,
            "success": True,
            "result": result,
        }

    except Exception as exc:

        return {
            "tool": name,
            "success": False,
            "error": str(exc),
        }


# ============================================================
# TURN 1
# GET CLAIM
# ============================================================

async def get_claim_step(ctx):

    ctx.next_turn()

    print("→ get_claim()")

    result = await run_tool(
        "get_claim",
        get_claim,
        ctx.claim_id,
    )

    if not result["success"]:
        raise RuntimeError(
            f"get_claim failed: {result['error']}"
        )

    ctx.claim = result["result"]

    ctx.evidence.add(
        ctx.turn,
        "get_claim",
        ctx.claim,
    )

    ctx.tool_history.append(
        {
            "turn": ctx.turn,
            "tool": "get_claim",
        }
    )

    return ctx.claim


# ============================================================
# TURN 2
# CLAIM-LEVEL INDEPENDENT CHECKS
# ============================================================

async def claim_level_checks(ctx):

    ctx.next_turn()

    claim = ctx.claim

    member_id = get_value(
        claim,
        "member_id",
    )

    hospital_id = get_value(
        claim,
        "hospital_id",
    )

    date_of_service = get_value(
        claim,
        "date_of_service",
    )

    lines = get_value(
        claim,
        "lines",
        "line_items",
        default=[],
    )

    narrative = get_value(
        claim,
        "narrative",
        "claim_narrative",
        default="",
    )

    print(
        "→ lookup_policy()"
    )

    print(
        "→ lookup_hospital()"
    )

    print(
        "→ check_duplicate_claim()"
    )

    print(
        "→ check_narrative_risk()"
    )

    # These do NOT depend on each other.
    tasks = [

        run_tool(
            "lookup_policy",
            lookup_policy,
            member_id,
        ),

        run_tool(
            "lookup_hospital",
            lookup_hospital,
            hospital_id,
        ),

        run_tool(
            "check_duplicate_claim",
            check_duplicate_claim,
            member_id,
            hospital_id,
            date_of_service,
            lines,
        ),

        run_tool(
            "check_narrative_risk",
            check_narrative_risk,
            narrative,
        ),
    ]

    results = await asyncio.gather(*tasks)

    for result in results:

        if not result["success"]:

            print(
                f"⚠ {result['tool']} failed: "
                f"{result['error']}"
            )

            continue

        tool = result["tool"]
        value = result["result"]

        ctx.evidence.add(
            ctx.turn,
            tool,
            value,
        )

        ctx.tool_history.append(
            {
                "turn": ctx.turn,
                "tool": tool,
            }
        )

        if tool == "lookup_policy":
            ctx.policy = value

        elif tool == "lookup_hospital":
            ctx.hospital = value

        elif tool == "check_duplicate_claim":
            ctx.duplicate = value

        elif tool == "check_narrative_risk":
            ctx.narrative_risk = value

    return results


# ============================================================
# TURN 3
# LINE-LEVEL CHECKS
# ============================================================

async def line_level_checks(ctx):

    ctx.next_turn()

    claim = ctx.claim

    lines = get_value(
        claim,
        "lines",
        "line_items",
        default=[],
    )

    attached_documents = get_value(
        claim,
        "attached_documents",
        "documents_attached",
        "documents",
        default=[],
    )

    policy_id = get_value(
        get_value(
            ctx.policy,
            "policy",
            default=ctx.policy,
        ),
        "policy_id",
    )

    if not policy_id:
        raise RuntimeError(
            "Policy ID not found. "
            "Cannot perform line coverage checks."
        )

    print(
        f"→ Running line checks for {len(lines)} line(s)"
    )

    tasks = []

    for line in lines:

        code = get_value(
            line,
            "procedure_code",
            "code",
        )

        if not code:
            continue

        # Coverage and required-document checks
        # are independent for the same line.
        tasks.append(
            run_tool(
                f"check_line_coverage:{code}",
                check_line_coverage,
                code,
                policy_id,
            )
        )

        tasks.append(
            run_tool(
                f"check_required_documents:{code}",
                check_required_documents,
                code,
                attached_documents,
            )
        )

    results = await asyncio.gather(*tasks)

    for result in results:

        if not result["success"]:

            print(
                f"⚠ {result['tool']} failed: "
                f"{result['error']}"
            )

            continue

        tool = result["tool"]
        value = result["result"]

        ctx.evidence.add(
            ctx.turn,
            tool,
            value,
        )

        ctx.tool_history.append(
            {
                "turn": ctx.turn,
                "tool": tool,
            }
        )

        if tool.startswith(
            "check_line_coverage:"
        ):

            code = tool.split(":", 1)[1]

            ctx.coverage[code] = value

        elif tool.startswith(
            "check_required_documents:"
        ):

            code = tool.split(":", 1)[1]

            ctx.documents[code] = value

    return results


# ============================================================
# TURN 4 — CONDITIONAL PREAUTHORISATION
# ============================================================

async def preauthorisation_step(ctx):

    claim = ctx.claim

    member_id = get_value(
        claim,
        "member_id",
    )

    date_of_service = get_value(
        claim,
        "date_of_service",
    )

    required_codes = []

    for code, result in ctx.coverage.items():

        if result is None:
            continue

        requires = get_value(
            result,
            "requires_preauthorisation",
            "requires_preauthorization",
            "preauthorisation_required",
            "preauthorization_required",
            default=False,
        )

        if requires:
            required_codes.append(code)

    if not required_codes:

        print(
            "\n→ No preauthorisation required"
        )

        return

    ctx.next_turn()

    print(
        "→ Preauthorisation required for:",
        required_codes,
    )

    tasks = []

    for code in required_codes:

        tasks.append(
            run_tool(
                f"find_preauthorisation:{code}",
                find_preauthorisation,
                member_id,
                code,
                date_of_service,
            )
        )

    # Multiple required preauthorisations are independent.
    results = await asyncio.gather(*tasks)

    for result in results:

        if not result["success"]:

            print(
                f"⚠ {result['tool']} failed"
            )

            continue

        tool = result["tool"]

        code = tool.split(":", 1)[1]

        value = result["result"]

        ctx.preauthorisations[code] = value

        ctx.evidence.add(
            ctx.turn,
            tool,
            value,
        )

        ctx.tool_history.append(
            {
                "turn": ctx.turn,
                "tool": tool,
            }
        )


# ============================================================
# DECISION LOGIC
# ============================================================

def calculate_totals(ctx):

    lines = get_value(
        ctx.claim,
        "lines",
        "line_items",
        default=[],
    )

    approved = 0
    refused = 0
    resolved = 0

    for line in lines:

        code = get_value(
            line,
            "procedure_code",
            "code",
        )

        amount = get_value(
            line,
            "amount",
            "claimed_amount",
            "claim_amount",
            "total_amount",
            default=0,
        )

        coverage = ctx.coverage.get(code)

        covered = get_value(
            coverage,
            "covered",
            "is_covered",
            default=False,
        )

        preauth = ctx.preauthorisations.get(code)

        if preauth is not None:

            status = get_value(
                preauth,
                "status",
                default="not_found",
            )

            if status != "valid":
                covered = False

        documents = ctx.documents.get(code)

        documents_complete = get_value(
            documents,
            "complete",
            "all_required",
            "documents_complete",
            default=True,
        )

        if covered and documents_complete:

            approved += amount

        else:

            refused += amount

        resolved += 1

    ctx.approved_total = approved
    ctx.refused_total = refused

    return resolved


def make_decision(ctx):

    # --------------------------------------------------------
    # Duplicate guard
    # --------------------------------------------------------

    if get_value(
        ctx.duplicate,
        "is_duplicate",
        default=False,
    ):

        return {
            "decision": "escalate",
            "trigger": "duplicate_claim",
            "reason": "Potential duplicate claim detected.",
        }

    # --------------------------------------------------------
    # Narrative guard
    # --------------------------------------------------------

    if get_value(
        ctx.narrative_risk,
        "high_risk",
        "is_high_risk",
        default=False,
    ):

        return {
            "decision": "ESCALATE",
            "trigger": "narrative_risk",
            "reason": "Narrative requires further review.",
        }

    # --------------------------------------------------------
    # Missing documents
    # --------------------------------------------------------

    missing = []

    for code, result in ctx.documents.items():

        complete = get_value(
            result,
            "complete",
            "all_required",
            "documents_complete",
            default=True,
        )

        if not complete:

            missing_items = get_value(
                result,
                "missing",
                "missing_documents",
                default=[],
            )

            if missing_items:
                missing.extend(missing_items)
            else:
                missing.append(
                    f"Required documents for {code}"
                )

    # --------------------------------------------------------
    # Invalid preauthorisation
    # --------------------------------------------------------

    invalid_preauth = []

    for code, result in ctx.preauthorisations.items():

        status = get_value(
            result,
            "status",
            default="not_found",
        )

        if status != "valid":
            invalid_preauth.append(code)

    # Missing/invalid evidence → request specific item.
    if missing or invalid_preauth:

        reasons = []

        if missing:
            reasons.append(
                "Missing documents: "
                + ", ".join(map(str, missing))
            )

        if invalid_preauth:
            reasons.append(
                "Missing/invalid preauthorisation: "
                + ", ".join(invalid_preauth)
            )

        return {
            "decision": "REQUEST_DOCUMENT",
            "trigger": "missing_evidence",
            "reason": "; ".join(reasons),
            "missing": missing,
        }

    # --------------------------------------------------------
    # Calculate line totals
    # --------------------------------------------------------

    resolved = calculate_totals(ctx)

    # --------------------------------------------------------
    # No payable amount
    # --------------------------------------------------------

    if ctx.approved_total == 0:

        return {
            "decision": "REJECT",
            "trigger": "no_covered_lines",
            "reason": "No claim lines are payable.",
            "lines_resolved": resolved,
        }

    # --------------------------------------------------------
    # Partial approval
    # --------------------------------------------------------

    if ctx.refused_total > 0:

        return {
            "decision": "APPROVE",
            "trigger": "partial_approval",
            "reason": "Some claim lines are payable while others are excluded.",
            "lines_resolved": resolved,
        }

    # --------------------------------------------------------
    # Full approval
    # --------------------------------------------------------

    return {
        "decision": "APPROVE",
        "trigger": "all_checks_passed",
        "reason": "All required checks passed.",
        "lines_resolved": resolved,
    }


# ============================================================
# ACTION GATE
# ============================================================

def action_gate(ctx):

    decision = ctx.decision

    if not decision:
        return False

    action = decision["decision"]

    # Request/escalate means the irreversible letter action
    # is not performed.
    if action not in {"APPROVE", "REJECT"}:

        print(
            "\n→ ACTION BLOCKED"
        )

        print(
            f"Decision: {action}"
        )

        return False

    # Explicit autonomy gate.
    if AUTONOMY_MODE == "confirm":

        print(
            "\n→ ACTION GATE"
        )

        print(
            "Decision letter is ready."
        )

        print(
            f"Decision: {action}"
        )

        print(
            f"Approved total: {ctx.approved_total}"
        )

        print(
            f"Refused total: {ctx.refused_total}"
        )

        # For the scripted project workflow we approve
        # the action automatically after the gate.
        return True

    if AUTONOMY_MODE == "act":
        return True

    return False


# ============================================================
# FINAL ACTION
# ============================================================

def issue_letter(ctx):

    if not action_gate(ctx):
        return None

    decision = ctx.decision

    lines_resolved = decision.get(
        "lines_resolved",
        0,
    )

    trigger = decision.get(
        "trigger"
    )

    missing = decision.get(
        "missing"
    )

    print(
        "\n→ issue_decision_letter()"
    )

    result = issue_decision_letter(
        ctx.claim_id,
        decision["decision"],
        lines_resolved,
        ctx.approved_total,
        ctx.refused_total,
        trigger,
        missing,
    )

    ctx.evidence.add(
        ctx.turn + 1,
        "issue_decision_letter",
        result,
    )

    ctx.tool_history.append(
        {
            "turn": ctx.turn + 1,
            "tool": "issue_decision_letter",
        }
    )

    return result


# ============================================================
# MAIN WORKFLOW
# ============================================================

async def process_claim(claim_id):

    ctx = WorkflowContext(
        claim_id=claim_id
    )

    print(
        "\n======================================"
    )

    print(
        f" CLAIM PROCESSING: {claim_id}"
    )

    print(
        "======================================"
    )

    # --------------------------------------------------------
    # TURN 1
    # --------------------------------------------------------

    await get_claim_step(ctx)

    if not ctx.claim:

        return {
            "claim_id": claim_id,
            "status": "CLAIM_NOT_FOUND",
        }

    # --------------------------------------------------------
    # TURN 2
    # --------------------------------------------------------

    await claim_level_checks(ctx)

    # --------------------------------------------------------
    # TURN 3
    # --------------------------------------------------------

    await line_level_checks(ctx)

    # --------------------------------------------------------
    # TURN 4 — CONDITIONAL
    # --------------------------------------------------------

    await preauthorisation_step(ctx)

    # --------------------------------------------------------
    # DECISION
    # --------------------------------------------------------

    ctx.decision = make_decision(ctx)

    print(
        "\n================ DECISION ================"
    )

    print(
        json.dumps(
            ctx.decision,
            indent=2,
            default=str,
        )
    )

    # --------------------------------------------------------
    # ACTION
    # --------------------------------------------------------

    letter = None

    if ctx.decision["decision"] in {
        "APPROVE",
        "REJECT",
    }:

        letter = issue_letter(ctx)

    # --------------------------------------------------------
    # FINAL RESULT
    # --------------------------------------------------------

    return {
        "claim_id": claim_id,

        "turns": ctx.turn,

        "decision": ctx.decision,

        "approved_total": ctx.approved_total,

        "refused_total": ctx.refused_total,

        "decision_letter": letter,

        "tool_history": ctx.tool_history,

        "evidence": ctx.evidence.export(),
    }


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    result = asyncio.run(
        process_claim("CLM-8842")
    )

    print(
        "\n\n============== FINAL RESULT =============="
    )

    print(
        json.dumps(
            result,
            indent=2,
            default=str,
        )
    )