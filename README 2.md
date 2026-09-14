# A2 Loop Handoff Package

This folder is a self-contained handoff package for the teammate building the loop for **PE6201 A2, Problem A**.

## What is included

- `demo_problem_a_tools.py`

  - a simple runnable demo of the Problem A tool chain

- `HANDOFF_FOR_LOOP_BUILDER.md`

  - the main integration note for the loop owner

- `tools/`

  - the upgraded Problem A tool package

- `A2_reference_data/data_A/`

  - the reference data needed by the tool package

## How to run

Open a terminal inside this folder and run:

```bash
python3 demo_problem_a_tools.py
```

To run a different claim:

```bash
python3 demo_problem_a_tools.py --claim-id CLM-8888
```

## Recommended reading order

1. `HANDOFF_FOR_LOOP_BUILDER.md`
2. `demo_problem_a_tools.py`
3. `tools/problem_a.py`

## Main entry points

- Tool package entry: `tools/problem_a.py`

- Demo runner: `demo_problem_a_tools.py`

## Notes

- Use `python3`, not `python`

- This package is designed for local demo and loop integration

- The demo runner is a simplified teaching runner, not the final full decision engine

