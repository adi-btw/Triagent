# Deploying the public demo

The repository builds one container (`Dockerfile`) holding the API, the UI, the embedding
model and a pre-built index. The container starts with `DEMO_MODE=true` and **no API key**.
It serves the UI's sample incidents from pre-computed answers (`data/demo_cache`) and refuses
anything else with HTTP 403, so the deployment can never call a paid model. The sections below
on rate limits and budgets only apply if you choose to add a `GEMINI_API_KEY`.

## What protects the API key

A public URL plus a paid key is a cost exposure, so demo mode (`app/demo.py`) adds three
layers:

| Layer | Default | Effect |
|---|---|---|
| Pre-seeded answers (`data/demo_cache`) | the two UI samples × three modes | Clicking a sample replays a real, earlier answer: instant and free |
| Per-visitor rate limit | `DEMO_REQUESTS_PER_IP_PER_HOUR=20` | HTTP 429 with `Retry-After` once a visitor exceeds it |
| Daily model budget | `DEMO_LLM_CALLS_PER_DAY=300` | Hard cap on calls that reach Gemini; cache hits don't count |

The daily cap bounds the worst case at 300 Flash-Lite calls of 3–4k tokens each. Multiply by
current Gemini pricing to get a dollar figure, and set a budget alert in Google AI Studio as
well. Limits live in process memory, which suits one small instance. More replicas would need a
shared store such as Redis.

The sample answers are keyed on the exact prompt, model and settings. If you change a sample
in `app/static/app.js`, the prompts, the corpus or the model, re-seed and commit:

```bash
python -m scripts.seed_demo_cache     # ~8 Gemini calls
```

CI checks this on every push. The `docker` job builds the image, starts it with an invalid
API key, and requires every sample in every mode to come back `ok`. A missing answer would
need a real call and fail.

## Option A: Render (recommended; deploys from GitHub)

1. Sign in at render.com with GitHub and grant access to this repository.
2. **New → Blueprint**, pick the repository. Render reads `render.yaml` (Docker runtime,
   free plan, health check on `/health`).
3. No secrets are needed. Don't add `GEMINI_API_KEY` unless you accept model costs.
4. Deploy. Later pushes to `main` redeploy automatically.

Memory: the app uses about 250 MB resident (measured locally), inside the free plan's 512 MB.
Free instances sleep after about 15 minutes idle, so the first visit after a pause takes up to a
minute to wake. That's fine for a portfolio link; the paid "starter" plan stays awake.

## Option B: Hugging Face Spaces (Docker)

1. Create a Space with SDK **Docker** (free CPU hardware is plenty).
2. No secrets needed (leave out `GEMINI_API_KEY` to keep it free).
3. A Space's README must start with front matter, so push a copy whose README begins with:
   ```yaml
   ---
   title: Triagent
   sdk: docker
   app_port: 7860
   ---
   ```
   then `git push` to the Space's git remote. The Dockerfile already listens on 7860 and runs
   as uid 1000, as Spaces require.

## Deep links

`/?sample=checkout&mode=agent` (or `mode=rag` / `no_retrieval`, `sample=vague`) loads a
sample and runs it, so a link in a résumé or README opens straight onto a finished report.

## Running the container locally

```bash
docker build -t triagent .
docker run -p 7860:7860 -e GEMINI_API_KEY=... triagent
# demo guardrails off:   -e DEMO_MODE=false
```
