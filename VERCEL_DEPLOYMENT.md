# PennyScope: Vercel deployment

## Import settings

- GitHub repository: `phoebeli00/newuipenny`.
- Production branch: `main` (after the deployment fixes are uploaded).
- Project Root Directory: repository root (`.`), **not** `original_app`.
- Use the repository-root `vercel.json` Services configuration. It declares
  only `frontend` (Next.js) and `backend` (FastAPI, `main:app`). Do not accept
  an additional detected service for the legacy root `agent_app.py`.
- Leave project-wide build/install/output overrides unset; use the per-service
  configuration and framework defaults. Frontend builds with `npm run build`.
- Enable Fluid Compute. The existing frontend function duration and configured
  backend duration are 420 seconds: use a plan supporting that limit (Pro or
  Enterprise). Hobby's 300-second limit cannot accommodate this configuration.
- Node.js: 22.x. The backend installs its own `requirements.txt`; do not select
  the root legacy application's requirements or run a persistent uvicorn server.

## Environment variables

Set these for each Vercel environment you intend to test (Preview/Production).
Keep all credentials server-only; never prefix them with `NEXT_PUBLIC_`.

Backend service:

```text
PENNYSCOPE_LLM_PROVIDER=bedrock
AWS_ACCESS_KEY_ID=<your Bedrock IAM access key ID>
AWS_SECRET_ACCESS_KEY=<your Bedrock IAM secret access key>
AWS_REGION=us-east-1
BEDROCK_MODEL_ID=us.meta.llama3-3-70b-instruct-v1:0
```

Use the same model/profile and region as the working local backend. Do not copy
credentials into the repository. If using temporary AWS credentials, also set
`AWS_SESSION_TOKEN`; for long-lived access keys leave it unset. The IAM identity
needs permission to invoke the chosen model/profile. Environment credentials
bypass the optional local `.secrets/aws_iam.json` file entirely.

Frontend service:

```text
NEXT_PUBLIC_BACKEND_MODE=live
```

The committed `original_app/.env.production` already supplies this public flag;
remove any Vercel `mock` override or set it explicitly to `live`.

**Do not set `BACKEND_URL` manually.** The existing service binding injects it at
runtime. Remove any old localhost or public-frontend URL override. Keep the
browser -> `/api/backend/[action]` -> FastAPI proxy path. No public backend
rewrite or CORS change is required. `BACKEND_API_KEY` is not required by the
current backend and does not enable authentication.

## Packaging

The backend build runs `python prepare_deployment.py`. It copies the canonical
repository-root `financial_tools.py` unchanged into the service directory. This
generated copy is ignored by Git. Function `includeFiles` explicitly includes
that copy and `routing_prompt.txt`; Python modules remain in the backend service.
The shared models, prompts, response contracts, and Next.js proxy are unchanged.

## Verification before and after deployment

Local checks:

```sh
python -m unittest discover -s original_app/tests -p 'test_*.py'
cd original_app
npm ci
npm test
npm run lint
npx tsc --noEmit
npm run build
```

The existing frontend tests expect a repository-root `.venv/bin/python` with the
backend requirements installed. Deployment does not depend on that local venv.
Deployment tests stage an isolated backend, remove the root calculator, and
verify app imports, four registries, runtime resources, routes, and health without
local credentials or network calls. Bedrock tests mock provider calls.

After manually deploying, check build logs show exactly two services and the
backend preparation command. Then submit a real financial question through the
browser to verify AWS permissions and model access, the internal binding, and
the rendered answer/worksheet. Local builds cannot validate your Vercel project
settings or AWS permissions. No deployment is performed by these checks.
