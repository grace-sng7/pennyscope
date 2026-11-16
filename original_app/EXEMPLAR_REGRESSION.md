# English exemplar regression — November 16, 2026

The complete 16-case source CSV was run before production changes and after each
set of shared base-input changes. B3 uses the one specified follow-up, `$500`, for
17 turns per batch. Every other case starts with fresh per-case caches.

Open [the case-by-case report](tests/regression_artifacts/report.html) or
[the complete machine-readable comparison](tests/regression_artifacts/comparison.json).
The per-turn comparison CSV and immutable raw runs/source snapshots are alongside
them. The original source CSV was read without modification.

## Results

- Baseline: 8 of 16 cases match the Sheet semantically; 8 of 17 turns match.
- Final: 15 of 16 cases match; 16 of 17 turns match.
- Final outcomes: 11 inspected calculations, 4 required clarifications, 1 explicit
  coverage gap, and 1 blocked calculation/review failure.
- S4 is an accepted coverage outcome, not a successful weekly calculation. The
  runtime preserves $60 weekly and eight deposits, reports that exact schedules
  exceed monthly-model coverage, and asks for no additional facts. The Sheet's
  $580 benchmark remains in the harness.
- D2 remains unresolved: complete inputs route/extract correctly, Python verifies
  two months and $15 interest, Main proposes a different interest total, and
  Inspector returns needs_input with an empty missing-input list. This produces
  HTTP 422 without exposing a final answer. It is a calculation/Inspector-policy
  problem, not a missing-input or coverage problem. Arithmetic/approval policy
  was left outside this base-input-rule change.

The raw baseline's original stricter S1 target-ID comparison is retained. The
report rescored it with the same semantic comparison used for all final records:
`monthly_contribution` and `required_monthly_savings` share the same monthly-required
solver. The identifier difference is documented, not counted as a numeric failure.
The report also records dedicated-fund and partial-expense representation differences.
No matching rule depends on identical wording.

## Shared causes and fixes

1. Collection encoding and units: native arrays/maps become JSON-string factor
   values without changing amounts; monthly fields and yes/no output units follow
   their definitions. Explicit nonmonthly units are not relabeled monthly.
2. Evidence-backed context: monthly replacement billing, named participants,
   explicit no-tax/no-tip, item ownership and today are represented without
   inventing financial quantities. A quote's source locator is corrected only
   when the unchanged quote occurs verbatim in an actual user message.
3. Follow-ups: a bare reply binds to the backend's own pending required question;
   it is not inferred from the exemplar answer key.
4. Required inputs: partial expense lists cannot satisfy complete spending.
   Purchase today requires no contribution input. Nonmonthly exact schedules are
   reported separately as coverage gaps. A supported rent difference is available
   before the missing baseline, with supporting factor IDs/values.
5. Native handoff: Main receives a raw input/binding plan, including the correct
   allocation versus settlement tool. Main still performs primary calculation;
   Python independently verifies. Structured draft factors receive the same
   representation normalization as extraction.
6. Supporting results: outputs from the same inspected scenario remain available
   alongside the main target. No financial formula, generated model, or Worksheet
   component was added or changed.

Routing needed no new financial-model rules. No changes were made to
`financial_tools.py`, `components/`, `app/` or `lib/` during this batch task.

## Harness boundary and capture

`tests/exemplar_batch.py` reads the English prompt and only the explicitly labeled
B3 test reply for backend submission. Expected model/factors/answers are kept in
the local oracle and comparison code. The Worksheet column is excluded entirely.
The normal API date/time fields and backend-generated extraction/state are passed
unchanged. The report builder audits every recorded request against this boundary.

Each turn captures selected model/target, accepted Given Information with IDs and
values, Inferred Information and supporting evidence, required Missing Information,
coverage gaps, and the result or next question. Empty lists remain explicit.
Rejected extraction drafts, Main results, verification values, Inspector decisions,
validation failures and HTTP statuses are retained for diagnosis. Accepted facts
are not fabricated from rejected model drafts. Source and backend hashes are saved.

The live runner exercises FastAPI endpoints with the actual configured Bedrock
provider. It does not mock routing, extraction, Main, verification or Inspector.
The comparison uses number tolerance 0.0051, units, roles, required-input/coverage
semantics, participant ownership and settlement direction. It checks requested
supporting results are actually returned, not only privately calculated.

## Reproduce

From the outer repository directory, with local provider configuration installed:

```sh
.venv/bin/python original_app/tests/exemplar_batch.py --phase new_run --source '/Users/phoebelin/Downloads/Penny Scope _ Formula and Exemplar Review - 2. English Exemplars.csv'
```

Use a new phase name: existing runs are never overwritten. These calls use the
configured provider and incur its normal usage. The report builder currently
compares the named retained runs `before`, `after`, `after_final`, `after_verified`:

```sh
.venv/bin/python original_app/tests/build_exemplar_report.py
```

Validation: 110 backend discovery tests, 25 calculator/agent tests, 6 extraction
HTTP tests, frontend tests (including 800 rendering combinations), and lint pass.
This is API/provider verification, not a browser-click or Worksheet review.
