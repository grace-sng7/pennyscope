# Question-specific financial factors

## Inspection findings

There was no separate reusable Savings Projection React component. Savings-specific
assumptions lived in `lib/calculator.ts`, `lib/mock/local-demo-calculation.ts`,
`backend_reference/savings_model.py`, and the original savings branch of
`backend_reference/orchestration.py`. They expected a fixed income/expenses/
savings/goal/deadline snapshot and produced fixed affordability metrics. The
independent Python savings function already supported all four calculation modes.

`Understood` and `WorkingSheet` grouped extraction assumptions using source alone.
`Understood` also suppressed missing monthly_surplus by name. This conflated a
rough estimate with a computed quantity and could show irrelevant savings inputs.
`AnswerCard` used the answer and formulas but did not render model factors.
`ResultView`, `InformationCard`, the presentation adapter, metrics and explanations
already supported variable-length arrays. They did not need per-model layouts.

## Compatible extension

Optional `model`, `target_variable`, and `factors` metadata extends extraction and
calculation responses. Existing fields and old responses remain supported.

Each factor uses existing `variable`, `value`, `unit`, `source`, `source_detail`,
plus `role` (known/derived/missing) and optional `relevant` (default true).
The target is separate from role. A contribution can be known in a projection and
derived when solving the inverse question. Source remains separate too: a rough
estimate may be known with source=inferred; it is not relabeled as verified math.
Structured factors retain the existing JSON-string convention. Names such as
monthly_expenses and goal_amount are retained when already used. Native calculator
argument aliases are translated at the backend boundary, not in React.

The UI displays only relevant factors, groups them under You Told Me / I Worked
Out / Still Unknown, and identifies the target. Unknown target values are not
requested as input. Derived factors introduced by a calculation are read-only;
existing review/correction controls retain their bindings. Calculation values are
invalidated after edits rather than retained as current results.

## Components and model behavior

- Reused existing cards, answer containers, working sheet, disclosures, styling,
  metric arrays and review flow.
- Added one shared read-only `ModelResultDetails`/`FactorValue` renderer for scalar
  results and arbitrary structured categories, adjustments, items, participants,
  weights, amounts owed/paid and settlements. Four parallel layouts are unnecessary.
- Savings uses the same savings_goal model for affordability/shortfall, projected
  balance, required monthly contribution and time to goal. Required inputs vary
  with solve_for; income is not required to solve a contribution from savings,
  target and deadline. A deadline is not required to solve time to goal.
- Budget independently verifies totals and explicit category reductions.
- Bill splitting independently verifies equal/itemized/custom allocation and can
  verify settlements from the same allocation plus supplied amounts paid.
- Debt supports duration from a payment and required payment from a duration,
  plus interest and total-repayment results.
- Unsupported algebraic targets still require a supported verifier. This phase
  does not claim that every possible inverse of every factor is implemented.

The main Gemini stage still selects the model/target/roles, calculates and drafts.
Python independently checks the same supplied inputs; Inspector reviews the draft,
verification and interpretations; resolution formats verified result factors.
Gemini structured-output constraints require role metadata for new calls while
keeping the legacy response envelopes. Bounded stage retries and Inspector resume
behavior remain in place. Python does not choose the target or infer unknown facts.

No new sliders, slider interactions, LLM-generated React, styling system, or
Sherry automatic model generation were added. Existing legacy scenario controls
remain compatible; new factor-aware results return no parameter controls.

## Validation

New frontend checks cover a contribution changing roles, all four savings targets,
relevant/irrelevant factors, source-label preservation, legacy responses, arbitrary
structured budget/bill/debt values, safe text rendering and invalid metadata.
Python tests exercise independent verification in both savings/debt directions,
category adjustments, custom/itemized bills and settlements, missing facts, and
the unchanged main → verification → Inspector orchestration.

Run from this folder: npm test; npm run lint; npm run build -- --webpack.
Run backend tests from the outer folder using its .venv.


Recorded checks: frontend tests (including 800 legacy rendering combinations and
new factor-role/structured-result checks), lint, TypeScript/production build pass.
Backend tests pass: 39 integration/retry/factor tests, 7 extraction tests and 25
original calculator/agent tests (71 Python tests). A live reverse-savings check
returned 250 per month from savings=500, target=1500, months=4 without income or
spending and with no parameter controls. The opt-in live role-aware HTTP smoke test
is tests/live-factor-flow.py. The older live-flow.py/live-models.py scripts describe
the prior fixed-metric/slider live flow; use the role-aware smoke test for this phase.
Gemini can still return temporary 503 errors; bounded retries stop safely.

The final role-aware HTTP smoke test also passed through the original Next.js
proxy, extraction, main draft, Python verification, Inspector, and target-specific
response. Both original page routes returned HTTP 200. The first smoke attempt
exhausted transient 503 retries; the subsequent complete run passed. Browser
visual/click QA was not performed; component rendering and HTTP routes were tested.
