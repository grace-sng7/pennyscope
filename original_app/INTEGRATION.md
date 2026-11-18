# Integrated Penny Scope

The original main-branch screens, components, styling, frontend state, adapters,
and wire format are preserved. Source snapshot: f4754687d5b89de07cbe3ef3be2531a412d5e787.
This folder is an isolated local integration; nothing was pushed to GitHub.

## Run

From the outer pennyscope_agent folder, terminal 1:

```
source .venv/bin/activate
python -m uvicorn main:app --app-dir original_app/backend_reference --port 8000
```

Terminal 2:

```
cd original_app
npm run dev
```

Open http://localhost:3000 for the original main-branch homepage, or
http://localhost:3000/classic for the existing Guide/Quick Calculate screens.
The old Gradio prototype is separate, on port 7860.

The ignored original_app/.env.local enables live mode and points to port 8000.
Credentials are read only by Python from the outer .secrets/gemini.json file.
Neither credential values nor provider error bodies are logged or sent to the browser.

## Architecture

- extraction_service.py retains the original extraction/correction prompt and
  source labels, with an explicit scope extension for budget, bills and debt.
- gemini_gateway.py uses direct Gemini calls with the working configured model;
  at most three attempts with bounded exponential backoff and jitter are allowed for transient server/network failures and HTTP 429. Provider failures
  keep the existing UI retry behavior and never expose an unchecked draft.
- orchestration.py asks the main Gemini stage to choose a model, identify gaps,
  bind inputs to source facts, perform the primary calculation, and draft an answer.
- Python independently runs financial_tools.py on those bound inputs. Savings
  verifies available cash, projection, shortfall and remaining cash separately.
- A distinct Inspector Gemini call sees the draft, evidence, assumptions, Python
  results and numerical differences. Material ambiguities return needs_input;
  gaps return unsupported. Arithmetic-only corrections use Python's values silently.
- savings_model.present_verified formats the resolved plan in the original UI
  response structure. The original savings_model.calculate remains a legacy
  reference, but the live endpoint no longer calls it or uses its default plan.
- Slider requests reuse a successfully inspected scenario for the same question,
  facts, evidence, answers and metadata. Only explicit reviewed controls may vary.
  Input corrections change the scenario identity and require fresh review.
  Savings allocation cannot exceed reviewed permission. Invariant model assumptions
  remain visible; slider-specific facts/formulas are rebuilt from current values.

Reviewed scenarios live in a bounded process-memory cache (128 entries, 30 minutes).
A restart/expiry causes another LLM review. This local prototype does not persist
financial profiles or review records to disk, and does not add accounts.

Budget, savings, bill allocation/settlement and debt repayment verifiers are wired.
Unclear rules or missing evidence require clarification. Compound multi-model
plans and additional debt-comparison sliders are not implemented; do not assume
arbitrary financial questions are supported.

## Verification

From outer folder:

```
.venv/bin/python -m unittest test_agent_structure.py test_financial_tools.py
.venv/bin/python -m unittest discover -s original_app/tests -p 'test_*.py'
.venv/bin/python original_app/tests/python-extraction.py
```

From original_app: npm test; npm run lint; npm run build -- --webpack.
Opt-in live tests (use API quota, fictional inputs, both servers running):

```
.venv/bin/python original_app/tests/live-flow.py
.venv/bin/python original_app/tests/live-models.py
```

Live HTTP tests exercise the frontend proxy and Python/Gemini pipeline, not browser
clicks. Visual browser verification requires a functioning browser automation host.
The original BACKEND_CONTRACT.md's no-LLM rule for every /calculate request is
superseded locally: initial/materially changed requests run the two-stage review;
only approved slider updates remain deterministic and fast.

## Recorded verification (2026-11-10)

- 25 original calculator/agent tests, 18 new architecture/verification regression
  tests, and 7 original Python extraction route tests pass (50 Python tests).
- Original npm tests pass, including 800 synthetic response rendering combinations,
  backend-wire contracts, state/correction handling, and local answer parsing.
- ESLint and production build (`npm run build -- --webpack`) pass. The initial
  sandboxed Turbopack build could not bind a worker port; the production Webpack
  build completed successfully outside that sandbox restriction.
- Live HTTP tests through the Next.js proxy passed savings extraction, two-stage
  calculation review, protected-savings controls, subsecond slider updates,
  corrections and fresh review, plus budget, equal bill splitting, and debt payoff.
- Original components/, lib/, and app/ trees match the inspected upstream snapshot.
- Google intermittently returned HTTP 503. Bounded provider retries and the existing
  UI retry path were exercised; failed reviews do not expose final answers.
- Browser automation host was unavailable, so browser-click/visual QA remains
  unverified. HTTP page routes and upstream frontend rendering tests passed.


## Stage-local retry update

The live backend uses direct HTTPX REST calls, not the Google Gen AI SDK.
The installed HTTPX default transport sets retries=0, so gemini_gateway.py is
its only transient retry layer. If migrating to the Google SDK, disable either
its retries or this loop; do not stack them. Extraction's existing schema-repair
attempt is separate and runs only after a successful but invalid model response.

Transient HTTP 429/500/502/503/504, HTTPX timeout and connection failures get up to
3 attempts total per stage. Waits use equal jitter over an exponential delay
(base 0.75s, cap 3s). Retry-After seconds and HTTP dates are respected; a delay
that exceeds the remaining stage budget stops rather than retrying early.
There is a 190s scheduling budget per stage, with up to 60 seconds for each
AI response read. The proxy allows 280 seconds and the browser allows 420 seconds
so the two-stage calculation review can finish before either gives up. Permanent
4xx errors and malformed output are not transport-retried.

Retries resend the same input snapshot only to the failing stage. A completed
main draft and Python verification are retained in a separate bounded in-memory
pending-review cache when the Inspector is unavailable. The existing UI Retry
can then resume just the Inspector. Changing facts/corrections/parameters changes
the pending-review identity; different inputs never reuse an older draft. Both
caches have the same 30-minute TTL and 128-entry bound. Backend restart/expiry
requires fresh review; pending drafts are never final answers or slider approvals.
No screens, client state or wire response fields changed.

Logs use gemini_retry/gemini_failed/gemini_success with stage (extraction,
correction, main_calculation, inspector), random call ID, attempts, HTTP status,
exception category, retry delay and elapsed time. They omit credentials, prompts,
provider bodies and financial data. Failure/retry logs are warning-level;
success logs can be enabled by setting the gemini_gateway logger to INFO.

Fault-injection tests cover 503, 429, timeout, attempt/deadline exhaustion,
Retry-After, permanent errors, immutable stage inputs, secret-safe logs, and
resuming an exhausted Inspector through FastAPI without rerunning the main
calculation or Python verification. Existing frontend state/render tests remain
unchanged. No live Google failures are needed to test these cases.


## Dynamic factor UI update

See [UI_FACTOR_PLAN.md](UI_FACTOR_PLAN.md) for the inspected fixed-role assumptions,
the optional factor protocol, reused components, supported reverse calculations
and phase limits. The existing design and main → verification → Inspector pipeline
remain. New role-aware results contain no sliders. Existing legacy controls remain
supported. New Gemini extraction/calculation calls use a JSON Schema constraint
for the additive metadata, with the original envelopes retained.


## Longer timeout and Bedrock connection check

AI response reads now allow 60 seconds (previously 6), while connection, write and
pool timeouts remain bounded separately. Retries still apply only to the failed
stage, with at most three attempts and a 190-second scheduling budget per stage.
The Next.js proxy allows 280 seconds and the browser 420 seconds. A slow request
may therefore remain pending for several minutes rather than failing early.

The saved .secrets/bedrock.json was tested directly against Bedrock Converse in
us-east-1. AWS returned HTTP 403 with an invalid-credential diagnostic. No provider
switch was made. A current region-appropriate Bedrock API key must pass a test
before enabling that provider. Credential values were not printed.


## Active Bedrock IAM provider

Bedrock IAM authentication and the complete reverse-savings workflow passed live
checks. The active provider is now selected by `.secrets/llm_provider.json`
(`provider: bedrock`). IAM key ID, secret, optional session token, region and model
are read from `.secrets/aws_iam.json`; the old bearer-key bedrock.json is unused.
The selected model is the configured Llama 3.3 70B inference profile. Credentials
are signed with SigV4 by Boto3. SDK total_max_attempts=1 prevents duplicate retries;
the shared gateway retains stage-local backoff, logs and 60-second read timeouts.

Extraction, main LLM draft, Python verification, Inspector and resolution retain
the same response contract and existing screens. Bedrock receives explicit JSON
schema instructions; the configured Llama model uses validated JSON output rather
than Gemini's server-enforced responseJsonSchema mode. Schema failures still stop
unverified results; extraction retains one repair attempt with validation findings.
Contradictory old fixed-savings instructions were removed from the main prompt.

Gemini configuration remains available. To return to it, set provider to gemini
in llm_provider.json and restart Python so prior scenario caches are cleared.
PENNYSCOPE_LLM_PROVIDER may override the file for isolated tests. Bedrock usage is
billed to the AWS account. The public UI never receives the credential files.


## Selection-only modular refactor

The live /extract path now uses model_router -> Python factor_registry lookup ->
factor_selection, replacing the old combined extraction prompt. See
[SELECTION_WORKFLOW.md](SELECTION_WORKFLOW.md) for the implemented scope, retained
downstream behavior, state handling, registries, tests and live example outputs.
No calculator or downstream answer-generation refactor is included in this phase.
