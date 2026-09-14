# Handoff For Loop Builder

This note is for the teammate building the loop/orchestration layer for **PE6201 A2, Problem A**.

It explains:

- where the new tool package is
- how it relates to the original scaffold
- what each tool is for
- the recommended tool-call order
- what is already implemented and what is still simplified

## 1. Project Context

We are working on **Problem A: health insurance claim first response**.

The claim-processing agent should produce one of three outcomes only:

- `approve_in_principle`
- `request_document`
- `escalate`

The tool layer is designed around **structured evidence retrieval**, not document-style semantic RAG.

The main business idea is:

1. load one claim
2. retrieve contract and case facts
3. inspect each line item separately
4. check supporting evidence
5. check risk conditions
6. produce a final structured decision

## 2. Where The New Tools Are

The new standalone Problem A tool package is located at:

- `A2/tools/`

Files:

- `tools/problem_a.py`
- `tools/schemas.py`
- `tools/__init__.py`
- `tools/README.md`

There is also a demo runner at:

- `demo_problem_a_tools.py`

## 3. Relationship To The Original Scaffold

The original scaffold is still in:

- `A2/A2_scaffold/`

Important point:

- the new tool package does **not** overwrite `A2_scaffold/tools.py`
- it is a **separate business-oriented tool layer**
- you can import it directly into a custom loop
- or later map it back into scaffold-style tool dispatch if needed

So please treat:

- `A2_scaffold/tools.py` as the teaching/reference implementation
- `A2/tools/problem_a.py` as the upgraded Problem A tool layer

## 4. How To Import The Tools

If your loop code is placed under the `A2` root, you can import directly like this:

```python
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
```

## 5. Implemented Tool Set

The current tool set is:

- `get_claim`
- `lookup_policy`
- `lookup_hospital`
- `check_duplicate_claim`
- `check_line_coverage`
- `find_preauthorisation`
- `check_required_documents`
- `check_narrative_risk`
- `issue_decision_letter`

## 6. Tool Purpose Summary

### `get_claim(claim_id)`

Purpose:

- load the queue record for one claim

Reads from:

- `A2_reference_data/data_A/claims.json`

Returns:

- the exact claim record used as the starting point of the run

### `lookup_policy(member_id)`

Purpose:

- follow `member -> policy`
- return the member, the linked policy, and `remaining = annual_limit - used_to_date`

Reads from:

- `members.json`
- `policies.json`

Returns:

- `member`
- `policy`
- `remaining`

### `lookup_hospital(hospital_id)`

Purpose:

- retrieve hospital facts, especially `panel`

Reads from:

- `hospitals.json`

### `check_duplicate_claim(member_id, hospital_id, date_of_service, lines)`

Purpose:

- detect whether this claim is a true duplicate of an already decided case

Reads from:

- `decided_claims.json`

Important:

- duplicate matching is based on **facts**
- not on `claim_id`
- it matches:
  - `member_id`
  - `hospital_id`
  - `date_of_service`
  - `lines` (code + amount)

### `check_line_coverage(code, policy_id)`

Purpose:

- evaluate one procedure line against policy rules

Reads from:

- `procedures.json`
- `policies.json`

Returns:

- description
- whether preauthorisation is required
- whether the line is excluded
- the exclusion rule if present

### `find_preauthorisation(member_id, procedure_code, date_of_service)`

Purpose:

- check preauthorisation status for one procedure on the service date

Reads from:

- `preauthorisations.json`

Important:

- this tool returns explicit business status:
  - `valid`
  - `expired`
  - `not_found`

This is intentionally richer than the original scaffold version.

### `check_required_documents(procedure_code, attached_documents)`

Purpose:

- compare rule-required documents with the documents already attached to the claim

Reads from:

- `required_documents.json`

Returns:

- required documents
- attached documents
- missing documents
- `all_present`

### `check_narrative_risk(narrative)`

Purpose:

- detect obvious hostile narrative patterns

Current implementation:

- lightweight rule-based detection
- looks for prompt-injection-like language
- looks for fake tool-output-like text

Current risk labels:

- `prompt_injection`
- `fake_tool_output`
- `none`

### `issue_decision_letter(...)`

Purpose:

- package the final decision into a structured receipt-style object

Current behavior:

- validates allowed decision values
- returns structured final output
- does **not** send anything to an external system

## 7. Recommended Call Order

The recommended orchestration order is:

1. `get_claim`
2. `lookup_policy`
3. `lookup_hospital`
4. `check_duplicate_claim`
5. `check_narrative_risk`
6. for each line:
   - `check_line_coverage`
   - if `requires_preauth == True`, call `find_preauthorisation`
   - `check_required_documents`
7. aggregate line-level evidence
8. call `issue_decision_letter`

## 8. What Can Run In Parallel

After `get_claim`, these are usually independent:

- `lookup_policy`
- `lookup_hospital`
- `check_duplicate_claim`
- `check_narrative_risk`

After `lookup_policy`, line-level `check_line_coverage` calls can run independently for each line.

After each line coverage result:

- `check_required_documents` can run independently
- `find_preauthorisation` should run only when that line requires preauth

## 9. Suggested Loop Logic

At a high level, the loop should reason in this order:

### Stage 1: Load the claim

- get the claim record
- extract `member_id`, `hospital_id`, `date_of_service`, `documents`, `lines`, `narrative`

### Stage 2: Check claim-level blockers

- duplicate?
- narrative risk?
- policy active?
- service date within policy dates?
- claim total within remaining annual limit?

If any strong blocker is hit, the loop may stop early with `escalate`.

### Stage 3: Check each line item

For each line:

- what procedure is it?
- is it excluded?
- does it require preauthorisation?
- if yes, is preauthorisation valid?
- are required documents missing?

### Stage 4: Aggregate the case

- determine claim-level outcome
- preserve line-level evidence
- compute:
  - `approved_total`
  - `refused_total`
  - `lines_resolved`

### Stage 5: Final action

- call `issue_decision_letter(...)`

## 10. Current Demo Script

A demo runner already exists:

- `demo_problem_a_tools.py`

Run it from the `A2` root with:

```bash
python3 demo_problem_a_tools.py
```

Or for a specific claim:

```bash
python3 demo_problem_a_tools.py --claim-id CLM-8888
```

What it currently does:

- runs the tool chain in business order
- prints each intermediate tool result
- builds a simplified decision draft
- produces a final receipt

What it is good for:

- understanding tool behavior
- showing intermediate evidence
- testing loop expectations

What it is **not**:

- not the final official claim engine
- not a complete reproduction of all expected outcome logic

## 11. Key Differences vs The Original Scaffold

Compared with `A2_scaffold/tools.py`, the upgraded tool layer adds or changes:

- `check_coverage` -> renamed as `check_line_coverage`
- `get_preauthorisation` -> upgraded as `find_preauthorisation`
- explicit `valid / expired / not_found` status for preauth
- explicit duplicate result object with `is_duplicate`
- new `check_required_documents`
- new `check_narrative_risk`
- broader `issue_decision_letter` schema supporting all three outcomes

## 12. Current Simplifications

These are intentional and should be known by the loop owner:

### Decision logic is still simplified

The demo script includes a helper that builds a decision draft, but this is only a teaching/demo layer.

It should not be treated as the final official decision policy without review.

### Narrative risk detection is rule-based

The current detector is intentionally simple and explainable.

It is suitable for a first prototype, but may be extended later.

### No external side effects

`issue_decision_letter` returns a receipt object only.

It does not:

- write to disk
- call an API
- send a message

## 13. Recommended Next Step For Loop Integration

If you are building the loop, the safest next step is:

1. use the new `tools` package directly
2. preserve line-level evidence in the transcript/state
3. keep claim-level blockers separate from line-level decisions
4. stop early only for strong claim-level escalation conditions
5. leave the final decision policy readable and explicit

## 14. Quick Mapping Table

| Need | Use |
|---|---|
| Load one claim | `get_claim` |
| Find policy facts | `lookup_policy` |
| Check hospital network status | `lookup_hospital` |
| Check duplicate claim | `check_duplicate_claim` |
| Check one line against coverage rules | `check_line_coverage` |
| Check preauth state | `find_preauthorisation` |
| Check missing documents | `check_required_documents` |
| Check narrative safety | `check_narrative_risk` |
| Package final output | `issue_decision_letter` |

## 15. One-Sentence Summary

Use `A2/tools/problem_a.py` as the new business-oriented tool layer, and build the loop around claim-level blockers first, then line-level evidence gathering, then final structured decision packaging.
