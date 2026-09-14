import os
import re
import ast
import json
import requests
from typing import Literal, List, Dict, Any

from tools import (
    get_claim,
    lookup_policy,
    lookup_hospital,
    check_coverage,
    get_preauthorisation,
    issue_decision_letter,
)


class ClaimAgent:

    def __init__(self, backend: Literal["scripted", "live"] = "scripted"):

        self.backend = backend

        # Reference notebook shows legitimate runs around 4 turns.
        self.max_steps = 6

        self.history = []
        self.action_history = set()

        # ---------------------------------------------------------
        # OpenRouter configuration
        # ---------------------------------------------------------
        self.base_url = "https://openrouter.ai/api/v1/chat/completions"
        self.model = "meta-llama/llama-3.1-8b-instruct"

        # DO NOT hardcode the API key.
        # Set it in your environment:
        #
        # export OPENROUTER_API_KEY="your-key"
        #
        self.api_key = os.getenv("OPENROUTER_API_KEY")

        if self.backend == "live" and not self.api_key:
            raise ValueError(
                "OPENROUTER_API_KEY environment variable is not set."
            )

        # ---------------------------------------------------------
        # Runtime state
        # ---------------------------------------------------------
        self.claim_data = None
        self.policy_data = None
        self.hospital_data = None
        self.coverage_results = []
        self.preauth_results = []

    # =============================================================
    # LLM
    # =============================================================

    def execute_live_model(self, prompt: str) -> str:

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an automated health-insurance claims "
                        "assessor. Follow the available tools exactly."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0,
        }

        response = requests.post(
            self.base_url,
            headers=headers,
            json=payload,
            timeout=60,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"OpenRouter API error {response.status_code}: "
                f"{response.text}"
            )

        data = response.json()

        return data["choices"][0]["message"]["content"]

    # =============================================================
    # ACTION PARSER
    # =============================================================

    def parse_actions(self, model_response: str) -> List[Dict[str, Any]]:
        """
        Parse:

        Action: get_claim(claim_id="CLM-8842")
        Action: lookup_policy(member_id="M-2214")
        Action: check_coverage(
            procedure_code="47120",
            policy_id="POL-3310"
        )

        AST is used instead of regex so lists and quoted strings
        such as evidence=[...] are parsed safely.
        """

        actions = []

        for line in model_response.splitlines():

            line = line.strip()

            if not line.startswith("Action:"):
                continue

            expression = line[len("Action:"):].strip()

            try:
                tree = ast.parse(expression, mode="eval")

                if not isinstance(tree.body, ast.Call):
                    continue

                call = tree.body

                if not isinstance(call.func, ast.Name):
                    continue

                tool_name = call.func.id

                args = {}

                for keyword in call.keywords:

                    if keyword.arg is None:
                        continue

                    args[keyword.arg] = ast.literal_eval(keyword.value)

                actions.append({
                    "tool": tool_name,
                    "args": args,
                })

            except Exception as exc:

                print(
                    f"Could not parse action: {expression}\n"
                    f"Reason: {exc}"
                )

        return actions

    # =============================================================
    # CONTEXT
    # =============================================================

    def build_system_prompt(self, claim_id: str) -> str:

        return f"""
You are an automated health-insurance claims assessor.

You are processing claim: {claim_id}

You MUST use ONLY these tools:

1. get_claim(claim_id)
2. lookup_policy(member_id)
3. lookup_hospital(hospital_id)
4. check_coverage(procedure_code, policy_id)
5. get_preauthorisation(member_id, procedure_code)
6. issue_decision_letter(
       case_id,
       decision,
       reason,
       evidence
   )

IMPORTANT RULES:

1. Begin with get_claim using the supplied claim_id.

2. DO NOT invent member IDs, hospital IDs, policy IDs,
   procedure codes, amounts, dates or any other values.

3. After get_claim, derive:
   - member_id
   - hospital_id
   - ALL procedure codes
   - date of service
   - all line amounts
   directly from the result.

4. Every claim line MUST receive its own check_coverage call.

5. All independent coverage checks should be issued together
   in the same turn.

6. lookup_policy must use the member_id obtained from get_claim.

7. lookup_hospital must use the hospital_id obtained from get_claim.

8. Do not call get_preauthorisation unless a coverage result says:
   requires_preauth = true.

9. Call get_preauthorisation ONLY for the specific lines that
   require it.

10. Do not issue a decision until all required checks have
    completed.

11. An excluded line does NOT automatically mean the entire
    claim is escalated.

12. The final reason must contain:
    - disposition for EVERY claim line
    - total claimed amount
    - applicable coverage information
    - exclusion rule where a line is excluded
    - pre-authorisation result where required
    - relevant policy/hospital findings

13. Never assume a missing or ambiguous tool result.

14. If required information is missing, say so and escalate.

15. The final decision may ONLY be:
    - approve_in_principle
    - request_document
    - escalate

16. issue_decision_letter is the final gated action.

Respond in this format:

Thought: concise reasoning
Action: tool_name(arg="value")

You may issue multiple independent Action lines in one turn.
"""

    # =============================================================
    # TOOL EXECUTION
    # =============================================================

    def execute_tool(
        self,
        action: Dict[str, Any]
    ) -> Any:

        tool_name = action["tool"]
        args = action["args"]

        # ---------------------------------------------------------
        # get_claim
        # ---------------------------------------------------------

        if tool_name == "get_claim":

            claim_id = args.get("claim_id")

            if not claim_id:
                raise ValueError("get_claim requires claim_id")

            # Only allow the requested claim.
            result = get_claim(claim_id)

            self.claim_data = result

            return result

        # ---------------------------------------------------------
        # lookup_policy
        # ---------------------------------------------------------

        elif tool_name == "lookup_policy":

            member_id = args.get("member_id")

            if not member_id:
                raise ValueError(
                    "lookup_policy requires member_id"
                )

            # Prevent fabricated member IDs.
            if self.claim_data:

                expected_member = self.claim_data.get("member_id")

                if expected_member and member_id != expected_member:

                    raise ValueError(
                        f"Invalid member_id '{member_id}'. "
                        f"Expected '{expected_member}'."
                    )

            result = lookup_policy(member_id)

            self.policy_data = result

            return result

        # ---------------------------------------------------------
        # lookup_hospital
        # ---------------------------------------------------------

        elif tool_name == "lookup_hospital":

            hospital_id = args.get("hospital_id")

            if not hospital_id:
                raise ValueError(
                    "lookup_hospital requires hospital_id"
                )

            # Prevent fabricated hospital IDs.
            if self.claim_data:

                expected_hospital = self.claim_data.get(
                    "hospital_id"
                )

                if (
                    expected_hospital
                    and hospital_id != expected_hospital
                ):
                    raise ValueError(
                        f"Invalid hospital_id '{hospital_id}'. "
                        f"Expected '{expected_hospital}'."
                    )

            result = lookup_hospital(hospital_id)

            self.hospital_data = result

            return result

        # ---------------------------------------------------------
        # check_coverage
        # ---------------------------------------------------------

        elif tool_name == "check_coverage":

            procedure_code = args.get("procedure_code")
            policy_id = args.get("policy_id")

            if not procedure_code:
                raise ValueError(
                    "check_coverage requires procedure_code"
                )

            if not policy_id:
                raise ValueError(
                    "check_coverage requires policy_id"
                )

            # -----------------------------------------------------
            # Validate procedure code against real claim lines
            # -----------------------------------------------------

            if self.claim_data:

                valid_codes = {
                    str(line["code"])
                    for line in self.claim_data.get("lines", [])
                }

                if str(procedure_code) not in valid_codes:

                    raise ValueError(
                        f"Procedure {procedure_code} was not found "
                        f"in the actual claim."
                    )

            # -----------------------------------------------------
            # Validate policy ID against real policy result
            # -----------------------------------------------------

            if self.policy_data:

                policy = self.policy_data.get("policy", {})

                expected_policy = policy.get("policy_id")

                if (
                    expected_policy
                    and policy_id != expected_policy
                ):
                    raise ValueError(
                        f"Invalid policy_id '{policy_id}'. "
                        f"Expected '{expected_policy}'."
                    )

            result = check_coverage(
                procedure_code,
                policy_id,
            )

            self.coverage_results.append(result)

            return result

        # ---------------------------------------------------------
        # get_preauthorisation
        # ---------------------------------------------------------

        elif tool_name == "get_preauthorisation":

            member_id = args.get("member_id")
            procedure_code = args.get("procedure_code")

            if not member_id:
                raise ValueError(
                    "get_preauthorisation requires member_id"
                )

            if not procedure_code:
                raise ValueError(
                    "get_preauthorisation requires procedure_code"
                )

            # -----------------------------------------------------
            # Validate member
            # -----------------------------------------------------

            if self.claim_data:

                expected_member = self.claim_data.get("member_id")

                if (
                    expected_member
                    and member_id != expected_member
                ):
                    raise ValueError(
                        f"Invalid member_id '{member_id}'. "
                        f"Expected '{expected_member}'."
                    )

            # -----------------------------------------------------
            # Validate that this line really requires preauth
            # -----------------------------------------------------

            coverage = next(
                (
                    c
                    for c in self.coverage_results
                    if str(c.get("code")) == str(procedure_code)
                ),
                None,
            )

            if coverage is None:

                raise ValueError(
                    f"No coverage result exists for "
                    f"{procedure_code}."
                )

            if not coverage.get("requires_preauth", False):

                raise ValueError(
                    f"Pre-authorisation was not required for "
                    f"{procedure_code}."
                )

            result = get_preauthorisation(
                member_id,
                str(procedure_code),
            )

            self.preauth_results.append(result)

            return result

        # ---------------------------------------------------------
        # issue_decision_letter
        # ---------------------------------------------------------

        elif tool_name == "issue_decision_letter":

            case_id = args.get("case_id")
            decision = args.get("decision")
            reason = args.get("reason")
            evidence = args.get("evidence", [])

            if not case_id:
                raise ValueError(
                    "issue_decision_letter requires case_id"
                )

            if not decision:
                raise ValueError(
                    "issue_decision_letter requires decision"
                )

            if not reason:
                raise ValueError(
                    "issue_decision_letter requires reason"
                )

            if decision not in {
                "approve_in_principle",
                "request_document",
                "escalate",
            }:
                raise ValueError(
                    f"Invalid decision: {decision}"
                )

            # -----------------------------------------------------
            # IMPORTANT GATE:
            # Do not allow final decision before coverage checks
            # for every actual line.
            # -----------------------------------------------------

            if self.claim_data:

                expected_codes = {
                    str(line["code"])
                    for line in self.claim_data.get("lines", [])
                }

                checked_codes = {
                    str(c.get("code"))
                    for c in self.coverage_results
                }

                missing = expected_codes - checked_codes

                if missing:

                    raise RuntimeError(
                        "Decision blocked. Coverage was not checked "
                        f"for lines: {sorted(missing)}"
                    )

            # -----------------------------------------------------
            # IMPORTANT GATE:
            # Required preauthorisations must exist.
            # -----------------------------------------------------

            required_preauth = {
                str(c.get("code"))
                for c in self.coverage_results
                if c.get("requires_preauth")
            }

            completed_preauth = {
                str(r.get("procedure_code"))
                for r in self.preauth_results
            }

            # Some implementations may not include procedure_code
            # in the response. In that case, fall back to references
            # generated by the tool flow.
            missing_preauth = (
                required_preauth - completed_preauth
            )

            if missing_preauth:

                # If the response does not expose procedure_code,
                # use count-based validation.
                if len(self.preauth_results) < len(required_preauth):

                    raise RuntimeError(
                        "Decision blocked. Required "
                        "pre-authorisation checks are incomplete "
                        f"for: {sorted(missing_preauth)}"
                    )

            print(
                "--> AUTONOMOUS ACTION: "
                "issue_decision_letter passed the gate"
            )

            return issue_decision_letter(
                case_id,
                decision,
                reason,
                evidence,
            )

        # ---------------------------------------------------------
        # Unknown tool
        # ---------------------------------------------------------

        else:

            raise ValueError(
                f"Unknown tool requested: {tool_name}"
            )

    # =============================================================
    # OBSERVATION FORMAT
    # =============================================================

    def format_observation(
        self,
        tool_name: str,
        result: Any
    ) -> str:

        return (
            f"Observation from {tool_name}:\n"
            f"{json.dumps(result, indent=2, default=str)}"
        )

    # =============================================================
    # MAIN RUN
    # =============================================================

    def run(self, claim_id: str):

        print(
            f"--- Starting run for {claim_id} "
            f"on {self.backend} backend ---"
        )

        self.history = []
        self.action_history = set()

        self.claim_data = None
        self.policy_data = None
        self.hospital_data = None
        self.coverage_results = []
        self.preauth_results = []

        turn_count = 0

        system_prompt = self.build_system_prompt(claim_id)

        self.history.append(system_prompt)

        while turn_count < self.max_steps:

            turn_count += 1

            print(f"\n{'=' * 60}")
            print(f"[TURN {turn_count}]")
            print("=" * 60)

            # =====================================================
            # GET MODEL RESPONSE
            # =====================================================

            if self.backend == "scripted":

                response = self.scripted_response(
                    claim_id,
                    turn_count,
                )

            else:

                context = "\n\n".join(self.history)

                response = self.execute_live_model(
                    context
                )

            print(response)

            self.history.append(
                f"MODEL:\n{response}"
            )

            # =====================================================
            # PARSE
            # =====================================================

            actions = self.parse_actions(response)

            if not actions:

                print(
                    "No actions found. Halting safely."
                )
                break

            # =====================================================
            # DEDUPLICATION GUARDRAIL
            # =====================================================

            action_signature = json.dumps(
                actions,
                sort_keys=True,
                default=str,
            )

            if action_signature in self.action_history:

                print(
                    "GUARDRAIL TRIGGERED: "
                    "Duplicate action block detected."
                )

                break

            self.action_history.add(
                action_signature
            )

            # =====================================================
            # EXECUTE ACTIONS
            # =====================================================

            observations = []

            for action in actions:

                try:

                    result = self.execute_tool(
                        action
                    )

                    observation = self.format_observation(
                        action["tool"],
                        result,
                    )

                    print(
                        f"\n--> {action['tool']}"
                    )
                    print(
                        json.dumps(
                            result,
                            indent=2,
                            default=str,
                        )
                    )

                    observations.append(
                        observation
                    )

                except Exception as exc:

                    error = (
                        f"Tool execution failed for "
                        f"{action['tool']}: {exc}"
                    )

                    print(
                        f"\nERROR: {error}"
                    )

                    observations.append(error)

            # =====================================================
            # STORE OBSERVATION
            # =====================================================

            obs_string = (
                "OBSERVATIONS:\n"
                + "\n\n".join(observations)
            )

            self.history.append(
                obs_string
            )

            # =====================================================
            # STOP AFTER FINAL DECISION
            # =====================================================

            if any(
                a["tool"] == "issue_decision_letter"
                for a in actions
            ):

                print(
                    f"\nRun complete in "
                    f"{turn_count} turns."
                )

                break

        if turn_count >= self.max_steps:

            print(
                "\nGUARDRAIL TRIGGERED: "
                "Maximum steps reached."
            )

    # =============================================================
    # SCRIPTED BACKEND
    # =============================================================

    def scripted_response(
        self,
        claim_id: str,
        turn_count: int,
    ) -> str:

        """
        Dynamic scripted backend.

        Unlike your original version, no policy IDs,
        procedure codes or member IDs are hardcoded.

        The values are extracted from actual tool results.
        """

        # ---------------------------------------------------------
        # TURN 1
        # ---------------------------------------------------------

        if turn_count == 1:

            return (
                "Thought: I need the claim details first.\n"
                f'Action: get_claim(claim_id="{claim_id}")'
            )

        # ---------------------------------------------------------
        # TURN 2
        # ---------------------------------------------------------

        if turn_count == 2:

            if not self.claim_data:

                return (
                    "Thought: Claim data is unavailable, "
                    "so I cannot continue safely.\n"
                    'Action: issue_decision_letter('
                    f'case_id="{claim_id}", '
                    'decision="escalate", '
                    'reason="Required claim data unavailable", '
                    'evidence=["get_claim"]'
                    ')'
                )

            member_id = self.claim_data["member_id"]
            hospital_id = self.claim_data["hospital_id"]
            lines = self.claim_data["lines"]

            # We cannot know policy_id until lookup_policy returns.
            #
            # Therefore the scripted backend needs to make the
            # policy lookup first. But the reference groups this
            # with coverage checks conceptually because they are
            # independent AFTER policy is known.
            #
            # In live mode, the model naturally does this dependency.
            return (
                "Thought: I now have the real member and hospital "
                "identifiers. I need the policy and hospital data.\n"
                f'Action: lookup_policy(member_id="{member_id}")\n'
                f'Action: lookup_hospital(hospital_id="{hospital_id}")'
            )

        # ---------------------------------------------------------
        # TURN 3
        # ---------------------------------------------------------

        if turn_count == 3:

            if not self.claim_data or not self.policy_data:

                return (
                    "Thought: Required policy data is unavailable, "
                    "so I must escalate.\n"
                    f'Action: issue_decision_letter('
                    f'case_id="{claim_id}", '
                    'decision="escalate", '
                    'reason="Required policy data unavailable", '
                    'evidence=["get_claim", "lookup_policy"]'
                    ')'
                )

            policy = self.policy_data.get(
                "policy",
                {}
            )

            policy_id = policy.get(
                "policy_id"
            )

            if not policy_id:

                return (
                    "Thought: The policy response did not provide "
                    "a policy ID. I cannot safely continue.\n"
                    f'Action: issue_decision_letter('
                    f'case_id="{claim_id}", '
                    'decision="escalate", '
                    'reason="Policy ID missing from tool response", '
                    'evidence=["lookup_policy"]'
                    ')'
                )

            actions = []

            for line in self.claim_data.get(
                "lines",
                []
            ):

                code = line["code"]

                actions.append(
                    f'Action: check_coverage('
                    f'procedure_code="{code}", '
                    f'policy_id="{policy_id}")'
                )

            return (
                "Thought: I have the actual policy ID and all "
                "claim lines. Each line needs its own coverage check.\n"
                + "\n".join(actions)
            )

        # ---------------------------------------------------------
        # TURN 4+
        # ---------------------------------------------------------

        if turn_count == 4:

            # Find lines that require preauth.
            required = [
                c for c in self.coverage_results
                if c.get("requires_preauth")
            ]

            if required:

                member_id = self.claim_data["member_id"]

                actions = []

                for cov in required:

                    code = cov["code"]

                    actions.append(
                        f'Action: get_preauthorisation('
                        f'member_id="{member_id}", '
                        f'procedure_code="{code}")'
                    )

                return (
                    "Thought: Coverage identified "
                    "specific lines requiring pre-authorisation. "
                    "I will check only those lines.\n"
                    + "\n".join(actions)
                )

        # ---------------------------------------------------------
        # FINAL DECISION
        # ---------------------------------------------------------

        return self.build_final_decision(
            claim_id
        )

    # =============================================================
    # DECISION BUILDER
    # =============================================================

    def build_final_decision(
        self,
        claim_id: str
    ) -> str:

        """
        Used only by scripted backend.

        The final reason is generated from actual tool results,
        rather than hardcoded procedure codes.
        """

        if not self.claim_data:

            return (
                f'Action: issue_decision_letter('
                f'case_id="{claim_id}", '
                'decision="escalate", '
                'reason="Claim data unavailable", '
                'evidence=["get_claim"]'
                ')'
            )

        lines = self.claim_data.get(
            "lines",
            []
        )

        dispositions = []

        has_missing_preauth = False

        for cov in self.coverage_results:

            code = cov.get("code")

            if cov.get("excluded"):

                rule = cov.get(
                    "exclusion_rule"
                ) or "unspecified exclusion rule"

                dispositions.append(
                    f"Line {code}: refused due to exclusion "
                    f"{rule}."
                )

            elif cov.get("requires_preauth"):

                # Find preauth result corresponding to this line.
                preauth = next(
                    (
                        p for p in self.preauth_results
                        if p.get("reference")
                        and str(code) in str(
                            p.get("reference")
                        )
                    ),
                    None,
                )

                if preauth:

                    status = preauth.get(
                        "status"
                    )

                    if status == "none_found":

                        has_missing_preauth = True

                        dispositions.append(
                            f"Line {code}: pre-authorisation "
                            f"required but none found."
                        )

                    else:

                        dispositions.append(
                            f"Line {code}: covered and "
                            f"pre-authorisation verified."
                        )

                else:

                    has_missing_preauth = True

                    dispositions.append(
                        f"Line {code}: pre-authorisation "
                        f"verification incomplete."
                    )

            else:

                dispositions.append(
                    f"Line {code}: covered."
                )

        # ---------------------------------------------------------
        # Determine decision
        # ---------------------------------------------------------

        if has_missing_preauth:

            decision = "request_document"

        else:

            decision = "approve_in_principle"

        total = sum(
            line.get("amount", 0)
            for line in lines
        )

        reason = (
            f"Claim total: {total}. "
            + " ".join(dispositions)
        )

        evidence = [
            "get_claim",
            "lookup_policy",
            "lookup_hospital",
            "check_coverage",
        ]

        if self.preauth_results:

            evidence.append(
                "get_preauthorisation"
            )

        return (
            "Thought: All required checks are complete. "
            "I can now issue the gated decision.\n"
            "Action: issue_decision_letter("
            f'case_id="{claim_id}", '
            f'decision="{decision}", '
            f'reason={json.dumps(reason)}, '
            f'evidence={json.dumps(evidence)}'
            ")"
        )


# ================================================================
# MAIN
# ================================================================

if __name__ == "__main__":

    agent = ClaimAgent(
        backend="live"
    )

    agent.run(
        "CLM-8842"
    )
