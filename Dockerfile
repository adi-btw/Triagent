# Triagent web app as a single container: API + UI + a baked-in retrieval index.
#
#   docker build -t triagent .
#   docker run -p 7860:7860 -e GEMINI_API_KEY=... triagent
#
# The embedding model and the index are built into the image, so a cold start doesn't
# download 130 MB or re-embed the corpus. DEMO_MODE is on: per-visitor rate limits, a daily
# model budget, and the UI's sample incidents served from data/demo_cache (see app/demo.py).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Hugging Face Spaces runs containers as uid 1000; the app writes new cache entries.
RUN useradd --create-home --uid 1000 app
WORKDIR /home/app/triagent

COPY --chown=app pyproject.toml ./
COPY --chown=app app ./app
COPY --chown=app eval ./eval
COPY --chown=app scripts ./scripts
RUN pip install .

COPY --chown=app data ./data
USER app
RUN python -m scripts.ingest

# The demo cache is keyed on the exact prompt and model: these must match the values
# data/demo_cache was seeded with (python -m scripts.seed_demo_cache prints them).
ENV DEMO_MODE=true \
    LLM_PROVIDER=gemini \
    GEMINI_MODEL=gemini-3.5-flash-lite \
    GEMINI_THINKING_LEVEL=low \
    RETRIEVAL_MODE=hybrid \
    TOP_K=5 \
    PORT=7860

EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
