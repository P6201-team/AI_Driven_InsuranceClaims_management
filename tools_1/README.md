# Problem A Tools

This folder contains a standalone Problem A tool package for the A2 project.

## Files

- `schemas.py`: TypedDict-based input/output schema definitions

- `problem_a.py`: the 9 recommended Problem A tools

- `__init__.py`: convenient re-export layer

## Tool list

- `get_claim`

- `lookup_policy`

- `lookup_hospital`

- `check_duplicate_claim`

- `check_line_coverage`

- `find_preauthorisation`

- `check_required_documents`

- `check_narrative_risk`

- `issue_decision_letter`

## Design notes

- The package reads from `A2_reference_data/data_A`

- Returned values follow the explicit schemas agreed for the project

- `find_preauthorisation` separates `valid`, `expired`, and `not_found`

- `check_duplicate_claim` returns an explicit `is_duplicate` flag

- `check_required_documents` compares rule-required documents with the claim's attached documents

- `check_narrative_risk` is a lightweight rule-based detector for hostile member narrative text

## Example

```python
from tools import get_claim, lookup_policy, check_line_coverage

claim = get_claim("CLM-8842")
policy_lookup = lookup_policy(claim["member_id"])
line_result = check_line_coverage("62480", policy_lookup["policy"]["policy_id"])
```

