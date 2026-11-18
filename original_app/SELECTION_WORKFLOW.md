# Model and factor selection refactor

Scope: routing, registry lookup, factor selection/extraction only. No calculator,
required-input engine, numeric normalization, Inspector or answer-generation logic
was replaced in this iteration. No UI layout/style files were changed.

## Inspected responsibility changes

The former extraction_service.py concatenated a savings-oriented base prompt and
several multi-model extensions. That single call selected a model, selected factors,
expressed derived quantities and sometimes suggested missing-input questions. Its
Bedrock wrapper added another set of extraction instructions.

That live combined prompt and its schema-repair loop were removed. The new path is:

1. model_router.route: one narrowly scoped LLM call; model_routing log stage.
2. extraction_service._extract_branch: validated route -> get_registry(model) in Python.
3. factor_selection.select: one narrowly scoped LLM call using only the selected
   registry and relevant state; factor_extraction log stage.
4. Python validates registry IDs, target, data shapes and envelope, merges retained
   supplied values, and adapts to the existing ExtractionResponse.

The router cannot extract factors or choose next actions. The factor response
cannot contain a model ID or next-stage instruction, use another model's factor
IDs, invent factor IDs, or calculate derived results. Neither call receives tools.
Unknown targets may be null; supplied facts are known, unsupplied relevant facts
are null/missing. An unsolved target is not a clarification question.

## Code boundaries

- routing_prompt.txt: the requested four definitions, examples and routing rules.
- model_router.py: strict routing output, including gap/ambiguous/multiple.
- factor_registry.py: four predefined Python registry objects with immutable
  factor definitions, supported targets, aliases and interpretation notes.
- factor_selection.py: selected-model prompt, constrained response schema and validation.
- extraction_service.py: execution order, correction/state handling and legacy envelope adapter.
- gemini_gateway.py / bedrock_transport.py: supplied stage-specific response schema
  and stage logs; provider retries/timeouts retained. Routing gets no factor/calculation
  wrapper instructions. Factor extraction gets no model-selection instructions.
- contract.py / main.py: optional history/profile inputs and forwarding; unresolved
  routing results stop before downstream calculation using existing response statuses.

Existing orchestration.py, dynamic_models.py, savings_model.py, financial_tools.py,
frontend components, bindings and response renderers are unchanged by this refactor.
The old root extraction.py notebook/reference artifact is not imported by the live path.

## State and unresolved routes

A concrete model selection is retained in selection_state. Ordinary explicit variable updates call only
factor extraction for that registry. Other follow-ups go to Router to distinguish continuation, new intent, or ambiguity. Existing effective
assumptions (including locally answered values) feed the next extraction. Earlier
known values omitted from a short correction are retained. Explicit supplied nulls
can clear previous values. History is retained up to twelve messages.

An unresolved route returns routing metadata with no selected model/factors:
- gap: existing unsupported response; no factor call or downstream calculation.
- ambiguous: a question about financial intent; no factor call.
- multiple: applicable IDs and a Python-composed question about which part to address.

A clarification of an unresolved route can run routing again. A clear new financial
intent reroutes and starts clean factors/history, even within the same model family.
Ambiguous transitions ask an intent question while retaining the active state; no
factor extraction runs until resolved.

## Registry coverage

The exact factor definitions/targets are in factor_registry.py. All requested factors
are present. Preserved additional existing identifiers are:
- budget: income_change (existing calculator scenario capability).
- savings aliases: monthly_spending, monthly_savings, months and target.
- bill aliases: total, people, method, tax, tip and weights.
- debt alias: balance -> principal_balance.

Aliases are accepted predefined IDs; they are not new generated factors. No factor
has a permanent input/output role. Entries/items/categories are JSON-array strings;
weights and amounts-paid/owed are JSON-object strings, preserving the current UI
value convention. Percent values retain their stated percentage (8% is 8, not .08).

## Explicit phase limits

This is two LLM calls for initial selection, not two calls for the entire existing
application. After selection, /calculate still uses the prior calculation/review
workflow, as requested. Its primary-calculation/Inspector behavior was not refactored.
The future deterministic missing-input stage has NOT been implemented here.
clarification_questions is therefore empty for concrete selection results; existing
downstream behavior remains responsible for financial clarifications for now.

Raw frequencies and dates are preserved. This phase does not annualize, compute
surplus, solve savings equations, allocate bills, or compute interest. Existing
calculator and formatter tests remain, and obsolete combined-extraction prompt
snapshot tests were replaced by tests for the actual two-stage runtime.

## Validation

Run from outer folder:
- .venv/bin/python -m unittest discover -s original_app/tests -p 'test_*.py'
- .venv/bin/python original_app/tests/python-extraction.py
- .venv/bin/python -m unittest test_agent_structure.py test_financial_tools.py

From original_app: npm test; npm run lint.

Tests cover exact execution order, all declared model targets, schema isolation,
unknown factors/targets, cross-model attempts, gap/ambiguous/multiple, raw frequency,
history/profile filtering, correction state, and real HTTP envelope compatibility.


## Recorded results

All four live Bedrock selection examples passed; abridged actual stage outputs are
saved in backend_reference/examples/selection-samples.json. The selected targets
remain null/missing, as this phase intentionally does not calculate them.

Initial selection has two logical LLM calls. A bounded pending-route cache keeps
an already validated route if factor extraction fails, so UI Retry resumes only
factor extraction. Entries expire after 30 minutes and are capped at 128; changed
question/context/profile/date uses a different key. A normal completed selection
removes its pending entry. Transport retries remain stage-local.

Python may materialize an empty display row for the explicitly selected target;
this is not an input requirement or a computed value. Format normalization is
limited to explicit method-label casing and literal representations such as
"five months" -> value 5 / unit months, or "$1,200" -> numeric 1200. No frequency,
percentage or financial arithmetic is performed; 8% stays 8, not 0.08.

The new selection path and existing backend tests pass (66 discovery tests plus
6 standalone extraction HTTP tests). The 25 original calculator tests, original
frontend suite including 800 render combinations, and lint pass. No production
financial calculators or downstream result generators were edited.


## Selection regression fixes

Generic monthly spending/income uses total factors; fixed/variable buckets and
entry tags require explicit category evidence. Regular timing alone is insufficient.
Known factors carry checked source evidence from user text, profile or retained
state. Numeric leaves (including structured values) must be supplied literals;
computed amounts, percentage conversions and fabricated amounts are rejected before
entering known state. Literal currency/count formatting remains supported. This is
a provenance guard, not a general semantic proof of every LLM interpretation.

Follow-up intent checks use the separate Router, followed by Python registry lookup;
ordinary explicit assignments use a deterministic continuation fast path. New intents
clear prior question factors/history. Ambiguous transitions preserve state and ask
clarification without invoking the extractor. Pending transition text is retained
when the user clarifies intent.

Actual Bedrock outputs are recorded in
backend_reference/examples/selection-fixes-runtime.json (four initial questions plus
budget-to-bill transition). All five passed. The budget returned monthly_spending
1650, raw biweekly income 900 without a fixed
category, and recurring_cost 90. The bill transition returned only total_bill 120,
participants 4, split_method equal and null amounts_owed; no computed 30 or old factors.

Validation after fixes: 74 backend discovery tests, 6 extraction HTTP tests,
25 original calculator/agent tests, frontend tests and lint passed.
Calculators, downstream orchestration/answer generation and UI were unchanged.


## Calculation targets in the UI

The backend target_variable and target factor rows remain unchanged in state.
The UI excludes the selected target from factor review chips, working-sheet rows,
result factor details, and missing-input questions. Null target rows are not user
inputs. Solved targets continue to appear in the existing answer headline/detail.
Known factors, genuinely missing inputs, source labels, styles, and binding indices
are preserved. No routing, extraction or financial calculation code changed.

Validation: frontend component/adapter tests cover all 17 supported targets from
the Python registry across the four models, including null and solved targets,
retained state and genuine missing inputs. Frontend tests, lint, production build,
and 74 backend discovery tests pass.

## Resolved calculation handoff — November 16, 2026

This update extends the earlier selection-only phase through `/calculate`. It
supersedes the phase limit above that left missing-input detection entirely to
Main. The four model IDs, descriptions, evidence validator and Router remain.
Model generation is still deferred to later offline coverage evaluation.

Already present: one selected registry per request; ambiguous/multiple/gap paths;
registry-specific factor extraction; checked source evidence; correction merging;
new-intent rerouting; reverse calculators; Main primary math, independent Python
verification and Inspector review; bounded provider retries and scenario caches.

Changed:

- `factor_registry.py` owns target-specific required-input alternatives. Extraction
  and Main receive the existing model descriptions from `routing_prompt.txt`.
  Savings accepts contribution or stated surplus or income/spending, and reverse
  targets omit the quantity being solved. Budget scenarios accept stated monthly
  surplus or a supported complete income/spending representation. Bills select
  prerequisites by split method/settlement target; debt by payment/time/interest.
- `calculation_handoff.py` checks the selected target and prerequisites before
  Main. Missing target, conflicting aliases or missing prerequisites return one
  question. Gap remains unsupported; multiple/ambiguous remain intent questions.
  Target and intent answers resume the existing correction/extraction path.
- Main receives `resolved_selection` and still performs the primary calculation.
  An explicit `intent_mismatch` or changed model/target permits one Router plus
  evidence-validated Extraction reevaluation, then a second Main draft. A model
  change starts without old structured factors; original evidence, history and
  effective user corrections remain available. Compatible explicit edits/extra
  inputs are retained; incompatible factors are cleared. Same-model target
  changes also reextract. Main's concern is review context, never user evidence.
- Persistent disagreement returns one focused question before verification or
  Inspector. Matching model, target, solver mode, bindings and units are checked
  before Python verification. Only inspected results enter the scenario cache.
- The budget verifier adapter accepts explicit monthly surplus without inventing
  gross income or expenses. Equal bill splits accept anonymous participant counts
  and generate display identifiers in code. Existing native calculators remain.
- Pending Inspector reviews and approved caches retain the resolved request, so
  rerouted results/retries use the new model's evidence and do not rerun Main.
- Older clients without selected-model metadata retain the legacy calculation
  contract. No UI layout, financial model generation, bank connection or profile
  persistence was added.

Verification on November 16:

- 88 backend discovery tests pass (74 existing plus 14 handoff regressions).
- 25 root calculator/agent tests and 6 standalone extraction HTTP tests pass.
- `npm test` (including 800 render combinations) and `npm run lint` pass.
- Actual configured Bedrock provider through in-process FastAPI endpoints:
  recurring rent from $700 stated monthly surplus with an additional $500/month
  charge returned affordability=Yes; reverse savings from $200 to $1,200 over
  five months returned $200/month; budget-to-bill correction cleared budget facts
  and returned four $30 shares of a $120 equal dinner split.
- Deterministic provider fault injection: unresolved disagreement makes exactly
  two Main calls and one reevaluation (Router + Extraction), returns one question,
  never invokes Python verification and never caches an answer. Model-change,
  same-model target-change, correction retention, rerouted Inspector retry and
  all 17 registry targets' input-rule coverage also pass.

Run the live check explicitly with:
`.venv/bin/python original_app/tests/live-handoff.py` from the outer folder. It
uses fictional data and incurs configured provider usage. These are API/provider
checks, not browser-click or visual QA.

### Apartment suggestion regression fix — November 16

The homepage suggestion about moving from $1,000 rent to a $1,400/month apartment
reproduced an evidence-validation failure: Bedrock labeled the old rent as the
`fixed_costs` total without explicit category/total evidence. The validator remains
strict. Budget extraction now has `replaced_recurring_cost` to preserve the old
literal alongside `recurring_cost` for the new charge. A stronger example prevents
partial rent from becoming a complete expense total. An evidence-validation
failure permits one extraction-only repair with the same registry and original
facts; a second failure still stops. Schema/transport errors are not retried by
this repair path. Logs record only registry, check category and repair-used flag.

The verifier adapter applies new minus replaced charge; Main receives the adapter
arguments and an exact evidence-binding example. Main still calculates first.
For missing cash-flow evidence, the target-specific checker asks for current
monthly surplus as an alternative to the complete income/spending breakdown.

93 backend tests, 25 calculator/agent tests, 6 extraction HTTP tests, frontend tests
and lint pass. The exact apartment prompt passed live through the running Next.js
proxy, asked one current-surplus question, then accepted a fictional $700 surplus
follow-up and returned an inspected affordability result. An independent live Main
check used the literal 1,400 and 1,000 bindings and verified $300 remaining after
the $400 increase. Both local servers were left running with the fix loaded.

### Laptop suggestion regression fix — November 16

The suggestion with $2,400 income, $1,000 rent, about $600 other spending,
$900 savings and a $2,500 laptop by next March exposed another representation
gap: savings Extraction emitted $1,600 as a known expense total, but it was a
computed sum, not supplied evidence. The one repair repeated that sum.

The savings registry now accepts complete `spending_entries`; extraction retains
the separate expense literals. The existing savings-calculator adapter sums the
same entries independently after Main's primary calculation. Duplicate spending
representations and computed values bound to raw entries remain rejected. A null
value with inconsistent known/source labels is canonicalized to missing; this
never accepts or creates a numeric value, and the raw provider output is copied
before normalization.

Calendar deadlines remain literal text/date evidence. They do not satisfy an
integer calculator horizon. A separate explicit `contribution_months` input lets
the checker ask one contribution-count question without overwriting the original
deadline or inventing a duration. Supplied numeric-month deadlines continue to
work directly. Complete entries remain distinct from partial expense lists, and
existing savings holdings remain distinct from permission to use them.

99 backend tests, 25 calculator/agent tests, 6 extraction HTTP tests, frontend tests
and lint pass. The exact laptop prompt passed live through the running Next.js
proxy, returned one contribution-count question, then accepted a fictional
clarification of four monthly contributions and permission to use the $900
savings. Main, Python verification and Inspector returned affordability=Yes.
Both local servers remain running with the fix loaded. Browser-click QA was not
performed.

## Full English-exemplar batch — November 16

See [EXEMPLAR_REGRESSION.md](EXEMPLAR_REGRESSION.md) for the complete 16-case,
17-turn baseline, shared base-input-rule changes, retained reruns, report, and
reproduction commands. The original baseline completed before backend edits.
Semantic case matches improved from 8/16 to 15/16. S4 is an explicit coverage gap
accepted by the Sheet; D2 remains a calculation/Inspector-policy failure with no
missing user input. No Worksheet files or shared calculator formulas changed.

## Main-owned answers and advisory verification

The active target-aware `/calculate` path now returns Main's requested result.
`answer_verification.main_response` adapts Main's structured final value to the
existing answer card envelope; derived display values are not replaced by Python.
The older fixed-input scenario/slider envelope remains a compatibility path.

`orchestration._disagreements` compares the requested target only. Inputs,
intermediates, metadata and prose do not affect verification. Monetary values use
cent precision with half-up rounding; named shares are compared per recipient,
and settlements retain payer/recipient identity. Incompatible target units or an
unavailable result yield an unverified annotation, not a solver-driven 422.

Verification uses the resolved user-input plan independently of Main's intermediate
fields. Its status is `matched`, `mismatch` or `unverified`. Inspector receives that
advisory result and cannot veto or replace a completed Main answer. Genuine missing
facts still return clarification from the input checks or Main before completion.
Both answer-card views show one accessible exclamation icon for mismatch/unverified
and no icon for matched. Caches retain the Main response and verification status.
No Worksheet component or financial calculator formula changed.

API tests and rendered-card tests cover $1,100/$1,100 without an icon,
Main $1,200/Python $1,100 retaining $1,200 with one icon, and unavailable Python
verification retaining Main with one icon. They also cover unrelated-field
differences, individual shares, monetary rounding, Inspector failures/vetoes,
required-input clarification and cached advisory responses. The new policy
supersedes the earlier Python-owned-number and Inspector-veto descriptions above.

The six-monthly-deposit wording also exposed a pre-Main coverage check that treated
any explicit deposit count as nonmonthly. A single explicitly monthly schedule now
maps its literal amount/count to monthly_contribution/contribution_months; no unit
conversion or financial arithmetic is performed during extraction. Nonmonthly
exact schedules retain their coverage-gap path.

Final checks: 120 backend discovery tests, 25 calculator/agent tests, 6 extraction
HTTP tests, frontend rendering/adapter tests, ESLint and TypeScript pass. The three
specified number/warning combinations are deterministic API and rendered-card
regressions. A real provider /calculate smoke check returned Main=1050 and Python=1100;
the API returned HTTP 200, retained 1050 in headline/factors, and marked mismatch,
including on cache replay. This was not reported as a matching-arithmetic live run.

### Main missing-input questions and independent sufficiency checks

A Main missing-input report now returns exactly its first focused question and
skips Inspector. Python checks the resolved target from supplied user facts, not
from the alleged missing value or an invented replacement. If the check is
unavailable or skipped, the question has no icon. If Python calculates the target,
the question remains visible and receives one icon with the message:
“The independent check found enough information to calculate.”

Verification metadata distinguishes question context from answer context. A
question check never turns into a final Python answer. Both conversational modes
preserve the single Main question; the classic question view uses the same warning
component. Answer comparison and Main-owned answer behavior remain unchanged.

Tests cover all three answer cases, both question-check outcomes, skipped checks,
and a missing-input report that relies on the already-resolved target. They assert
Inspector is not called for missing-input reports and verify icon count/message
through the frontend adapter and rendered components. 124 backend tests, the 25
calculator/agent tests, 6 extraction HTTP tests, frontend tests, lint and TypeScript
checks pass.


### Itemized ownership evidence and resilient chat

`extraction_evidence.py` now grounds each item price and its exact owner set in
user text, including active, possessive and separately priced/name-linked items.
Unsupported owners, prices, incomplete shared-owner sets and duplicate items are
rejected. Itemized input is identified by validated ownership, rather than a
whitelist of particular sentences. A custom/weighted label without weights is
canonicalized to itemized when validated item ownership supplies the allocation.
Combined tax and tip has its own supplied factor; neither extraction nor Main
invents separate tax/tip amounts. The native verifier accepts that pooled charge.

Main works through arithmetic before writing final factors. The itemized handoff
provides symbolic per-owner subtotal expressions using the supplied item amounts
and owner counts, with no Python-evaluated answer. Main evaluates the subtotals
and proportional charge itself. Python still only annotates the final answer.
There are no prompt-specific production values or answer lookups.

API boundaries recover structural failures with one plain-language LLM response
using the original question, confirmed facts and latest correction. If Main
already supplied usable text or a final result, it is retained without another
LLM call. If recovery also fails, known facts and the processing limitation are
shown; an internal failure is not presented as a missing user input. Plain
answers use the existing unverified warning; genuine questions do not acquire a
warning merely because a check was unavailable.

The chat accepts plain responses independently of card metadata. A React error
boundary displays existing Main text if the answer card throws; the working
sheet remains mounted. Confirmed worksheet facts survive extraction recovery.
Model coverage and the right-side worksheet design are unchanged.

Validation: 131 backend tests, 25 root calculator/agent tests, 6 extraction HTTP
tests, all frontend suites (including an actual forced React card exception),
ESLint and TypeScript checks pass. Fault injection covers rejected extraction,
invalid card metadata, card rendering failure, unavailable plain-language recovery
and genuine missing-input questions. Original and possessive-paraphrase provider
runs produced Main shares 24/24/12 matching Python, with no follow-up question.


### Question-scoped approaches for coverage gaps

The /calculate API now sends explicit routing gaps and unsupported registered
model results to `question_approach.calculate`. Ambiguous or multiple intents
still use the existing clarification path. Ordinary successful registered model
requests retain Router -> Extraction -> Main -> advisory verifier/Inspector.

The scoped Main call receives the four existing registry definitions, calculator
signatures and descriptions as examples. It drafts a formula, performs the primary
arithmetic, and returns a concise answer plus known/derived/missing factors.
Literal known values require verbatim evidence quotes, including separate quotes
for original amounts and corrected dates. Coverage gaps stay separate from actual
missing user inputs. One required missing input produces one focused question
without an unavailable-check warning.

A proposal is local to the request/conversation. It has no registered model ID,
executes no generated Python and writes no permanent registry entries. Since no
existing verifier covers its target, an answered proposal receives the existing
unverified `!`. Main's value remains the displayed answer. The answer box stays
concise; factors and calculation steps populate the existing worksheet. The plain
chat/card error-boundary fallback remains available, preserving grounded facts.

Gap corrections recalculate even when there are no registered extracted fields
to diff. Main's structured schema is explicitly treated as calculation (not
extraction) by the Bedrock adapter, so it includes derived target values.

Validation: 137 backend tests, 25 root calculator/agent tests, 6 extraction HTTP
tests, all frontend tests, lint and TypeScript checks pass. The actual React chat
handlers render $80 then $0 on a correction, update the worksheet and show one
warning per answer. Fault injection covers genuine missing input and malformed
proposal metadata while retaining Main text and grounded facts. Live requests
through the Next.js proxy returned “You need $80 before the bill is due.” for
checking=220, bill=300 on the 4th, paycheck=150 on the 6th; moving payday to the
3rd returned “You need $0 before the bill is due.” Both are cards with unverified
checks and no follow-up. A covered equal bill split retained bill_split, $30
per person and matched verification. Evidence is saved in
`tests/regression_artifacts/question_approach_live.json`.

### Grace presentation integration (reference 086b79b; base b7f1082)

Talk It Through retains the four-model backend and target-specific input checks.
`AnswerCard` remains a concise Main headline and the existing verification icon.
`AnswerSupporting` renders optional material below that answer, in a separate
section: Grace-style narrative, visuals, expandable math, and suggested questions.
The existing `send` correction/calculation flow handles suggestion clicks.

Carried over/adapted from Grace's `components/answer-visuals.tsx` and chart CSS:
StackedBar and its hover tooltip, exact-amount Legend, Figure, BudgetFigure,
funding-source breakdown, the monthly Timeline with hover and goal marker, and
OptionsTable as OptionsList. Timeline's table toggle is now an expandable list.
Reference-date labels include the year and do not use the browser's current month.
The narrative/explanation layout, math disclosure and what-if replies are preserved.
No tables are rendered in the integrated supporting content.

`answer_presentation.attach` builds optional presentation from the selected input
plan and the existing matched target check. Main remains the primary solver.
Presentation has no routing, required-input or model-registration authority.
For surplus-only budgets, the chart is explicitly labeled as money available
AFTER current expenses; it does not fabricate income or an expense breakdown.
Missing chart inputs omit that section instead of generating questions. Reverse
savings can show funding and timeline without a monthly budget chart.

Chart narratives are assembled from the exact current-plan fields. This avoids
mislabeling the remainder as the cost increase or describing an alternative plan
as the selected plan. On checked results without charts, Main's optional narrative
is accepted only with matching target metadata and grounded monetary figures;
otherwise a grounded explanation is used. No separate narration provider call is
needed. Alternative plans are clearly hypothetical and check monthly capacity
when supplied; otherwise the UI distinguishes goal arithmetic from affordability.
Shortfall scenarios include delay/lower-goal alternatives where supported.

Mismatched/unavailable verification preserves Main's answer and its `!` while
omitting potentially conflicting plots. Cash timing retains the scoped answer and
worksheet. The worksheet combines current extraction facts with calculation
factors, so a short Main factor list cannot erase known user facts.

Optional display data is parsed independently in `lib/answer-presentation.ts`.
Bad chart sections cannot invalidate the answer. Separate React error boundaries
protect the core answer, supporting content, and visuals. Tests force errors in
both the presentation builder and the actual visual component; Main's answer
remains visible, and an optional chart exception preserves narrative and replies.

A live rent check exposed a pre-existing citation issue: the extractor cited only
the NEW charge for an OLD rent amount. The extraction prompt now explicitly asks
for evidence containing the old amount. Evidence validation and the bounded repair
path remain unchanged; unsupported amounts are still rejected.

Validation:
- 146 backend tests, 25 root financial/agent tests and 6 extraction HTTP tests pass.
- All frontend suites, ESLint, TypeScript and diff whitespace checks pass.
- React-rendered regressions cover all chart types, legends, month labels, hover,
  monthly-details/math expansion, no tables, and real ChatApp suggestion handlers
  for both savings and budget corrections. Invalid optional payloads are omitted.
- Native Safari comparison used Grace's pinned frontend with a deterministic
  savings fixture, then the integrated frontend with the live backend/provider.
  Funding (2800 income + 200 savings), budget, timeline, narrative, and list-based
  alternatives were visually inspected. The savings nine-month suggestion updated
  the plan and worksheet in the browser; disclosures also worked.
- Live API checks returned savings visuals/narrative/replies, surplus-only rent
  300/month without a deadline question, reverse savings 200/month, bill shares
  30 without income questions, and cash timing 80 with unavailable verification.
  Recorded in `tests/regression_artifacts/grace_presentation_live.json`.
- Existing matched/mismatch/unavailable tests still prove Main 1100/no icon,
  Main 1200 versus Python 1100/one icon, and unavailable verification/one icon.

Intentionally not imported: saved profile, automatic price estimates and their
CostBreakdown UI, Grace's calculator-wins verification banner/comparison table,
and her standalone savings calculator/default allocation policy. Model-specific
presentation is currently savings/budget; bill/debt retain narrative/what-ifs and
worksheet math, and scoped cash timing uses its worksheet. Timeline plots are
bounded to 60 deposits; other available support still renders for longer horizons.
Grace's production provider/deployment was not exercised or modified.

The final native-browser budget suggestion changed the full new rent from 1400 to
1260/month, preserving the old rent of 1000 and stated surplus of 700. The result
updated from 300 to 440/month; narrative, cost segment (260), remaining-cash segment
(440), comparison list and worksheet all updated without an income/deadline question.

### Clarification-first correction (2026-11-18)

Grace's original skip handler also converts uncertainty into an estimation request.
That interaction is deliberately not carried over: skipping a required personal
fact leaves it unknown. The chat asks the next required question and pauses when
all remaining questions have been skipped, rather than inventing savings or
issuing an affordability verdict. Both quick and detailed modes respect this.

The selected registry target now supplies required-only unknowns in `/extract`
and `/correct`, before Main runs. Calendar language stays visible, but an unclear
number of deposits is asked explicitly. Existing supported input alternatives
remain valid: a contribution or surplus avoids unnecessary income/expense
questions; when income is already supplied, spending is the relevant next capacity
fact. Model coverage gaps remain separate from required personal facts.

Evidence validation and extraction instructions distinguish earnings from savings
contributions. A statement naming a financial role is handled as a correction,
not inserted into an unrelated pending field by the numeric reply shortcut.
Structured extraction recovery retains confirmed facts and asks required questions
before attempting plain-language recovery. Valid existing Main answers and the
advisory Python policy remain unchanged.

Validation: 152 backend tests and 25 root tests pass; npm test (including actual
ChatApp skip interactions in both modes), ESLint and TypeScript checks pass.
Six new mocked backend regressions cover earnings evidence, initial unknowns,
progressive answers, explicit contribution alternatives and failure recovery.
No provider is called by these regression tests. Live reproduction of the user's
financial prompt was blocked by automatic approval review because it would send
that financial data to the configured external provider; live extraction quality
for this new prompt is therefore not claimed as verified.

### Hosted screenshot: purchase today (2026-11-18)

The supplied PDF shows a $750 balance, $900 laptop and purchase today. The public
pennyscope.vercel.app bundles inspected read-only still contain Grace's fixed
five-input REQUIRED set, saved-profile UI and automatic estimation path. Its
bundled calculator rejects months <= 0 ("Deadline must be a positive whole number
of months."). These are not the currently integrated local chat/backend rules.
The screenshot's repeated requests for a deadline after replies of 0 are consistent
with this validation. The later generic error has no stack trace in the screenshot,
so its exact server exception cannot be established from this artifact.

Added offline regression coverage through /extract, /calculate and the actual
ChatApp answer card: savings 750, price 900, horizon 0 require no income/expenses or
additional deadline. Main receives the complete selection; Python agrees. No
external provider was called. All 153 backend tests pass, and the new frontend
interaction check passes. No production source or public deployment was changed
for this diagnosis; the public app still needs the integrated version deployed.

### Shared answer / schedule / worksheet presentation fixes (2026-11-18)

The integrated screenshots exposed presentation defects separate from the earlier
hosted Grace build: Main's yes/no explanation was relegated to an undisplayed
answer.detail, scoped weekly calculations bypassed presentation assembly, frontend
visual parsing required a matching Python check even for scoped timelines, and
nested worksheet list items inherited the top-level three-column grid.

Affordability now preserves Main's concise verdict sentence when its yes/no agrees
with the selected Main target. Missing narrative falls back to a readable verdict.
Today uses the existing zero-deposit funding chart and a today-specific explanation
and suggested questions, without pretending there is a monthly saving plan.
Scoped complete deposit schedules can show a narrative, suggestions and a list of
balances by deposit. The endpoint must agree with Main before the timeline renders;
Python remains unavailable/advisory and retains !. No model registration or new
Python verifier was introduced, and conflicting timelines are omitted.

One shared frontend fact formatter replaces raw entry labels/counts with amount,
frequency, number of deposits and shared ownership where available. Today replaces
0 months in the summary and worksheet. The worksheet uses plain readable summaries
and bounded columns; its grid selector now affects only top-level rows. Structured
facts remain unchanged in backend/state. All comparisons remain lists, not tables.

157 backend tests, npm test, ESLint and TypeScript checks pass. Coverage includes
today, weekly deposits, reverse and monthly savings, budget/rent, itemized bills,
debt, cash timing, optional failure and Main/Python disagreement. Added presentation
checks for weekly endpoints, mismatches/incomplete schedules, amount/frequency/count,
Today and funding charts. Native Safari visually checked server-rendered versions
of the actual components/styles using offline backend fixtures at a 300px worksheet
width; no external LLM requests were made. Updated local backend remains on 8000,
frontend on 3000. Existing rendered messages retain their old response payload;
start a new chat to request newly generated supporting content. Public deployment
was not changed.
