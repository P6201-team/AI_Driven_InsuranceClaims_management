# PE6201 A2 Problem A - Final Evaluation Data Package

This folder contains the complete fixture data and ground-truth answer key for the
final 40-case Problem A evaluation set.

## Package contents

| Path | Purpose |
| --- | --- |
| `make_fixtures_A.py` | Reproducible fixture generator. Team additions exist only in its `EXTRA_*` block. |
| `data_A/` | Generated Problem A JSON fixture tables used by the tools and evaluation harness. |
| `expected_outcomes_A.json` | Ground-truth answer key for all 40 claims. |
| `check_my_data.py` | Instructor-provided integrity checker. |
| `data_dictionary.json` | Instructor-provided field definitions and table relationships. |

`data_A/` contains:

- `claims.json` - 40 evaluation claims: 15 instructor-shipped and 25 team-added.
- `decided_claims.json` - claim history used for duplicate and near-duplicate checks.
- `hospitals.json` - panel status and country.
- `members.json` - member-to-policy joins.
- `policies.json` - status, coverage dates, annual limits, usage and exclusions.
- `preauthorisations.json` - member/procedure-specific authorisation windows.
- `procedures.json` - procedure descriptions and pre-authorisation flags.
- `required_documents.json` - procedure-specific document requirements.

## Final case composition

- Total evaluation cases: **40**
- Instructor-shipped cases: **15**, unchanged
- Selected team-added cases: **25**
- Decisions: **30 `approve_in_principle`**, **4 `request_document`**, **6 `escalate`**
- Non-approval/negative cases: **10 total**
- Newly added negative case: **CLM-9053 only**

Selected team-added case IDs:

```text
CLM-9002 CLM-9003 CLM-9004 CLM-9005
CLM-9012 CLM-9013 CLM-9014 CLM-9015
CLM-9021 CLM-9023 CLM-9024 CLM-9025
CLM-9031 CLM-9032 CLM-9033 CLM-9034
CLM-9041 CLM-9042 CLM-9043 CLM-9044 CLM-9045
CLM-9051 CLM-9053 CLM-9054 CLM-9055
```

Reserve cases intentionally excluded:

```text
CLM-9001 CLM-9011 CLM-9022 CLM-9035 CLM-9052
```

## Regenerate and validate

Run these commands from this folder:

```bash
python3 make_fixtures_A.py
python3 check_my_data.py
```

Expected final line:

```text
Your data hangs together.
```

Do not manually edit files inside `data_A/`. Change only the `EXTRA_*` block in
`make_fixtures_A.py`, regenerate the JSON, and rerun the checker.

## Ground-truth rules

The answer key follows the instructor routing table:

- `approve_in_principle`: every line resolves as covered, covered with a valid
  pre-authorisation, or clearly excluded.
- `request_document`: a required document or valid member/procedure-specific
  pre-authorisation is missing.
- `escalate`: policy lapse/date failure, annual-limit breach, exact duplicate,
  or instructions aimed at the system in member-supplied narrative.

`trigger` appears only on escalation rows. `missing` appears only on request rows.
Approval rows contain neither field.

## Validation record - 17 September 2026

The final package passed three independent checks:

1. **Instructor integrity checker:** all references resolve, IDs are unique,
   shipped records match their stored fingerprints, and every claim has one label.
2. **Structural audit:** exactly 40 claims and 40 labels exist; the 25 added IDs
   exactly match the reviewed selection; no reserve ID is present; answer-key
   decision-specific fields have the required shape.
3. **Deterministic regeneration audit:** fixtures regenerated from
   `make_fixtures_A.py` match the packaged `data_A/` files byte for byte, and the
   first 15 answer-key rows retain their original logical hash.

This package contains fixture and answer-key data only. No live-model battery was run.
