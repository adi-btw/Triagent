"""Pre-compute the public demo's answers for the UI's sample incidents.

    python -m scripts.seed_demo_cache        # needs GEMINI_API_KEY; ~8 LLM calls

Runs each sample incident from ``app/static/app.js`` through every mode with the real
model, through the LLM cache pointed at ``data/demo_cache``. Commit that folder: with
``DEMO_MODE=true`` the deployed app replays these answers, so a visitor clicking a
sample gets a real, instant result that costs nothing.

The sample text is parsed out of app.js (not copied here), so editing a sample in the UI
and forgetting to re-seed shows up as a cache miss, never as a stale answer. A cache entry
is keyed on the exact prompt, so the deployment must use the same model, thinking level,
corpus and retrieval settings as the seeding run. The script prints them.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from app.config import get_settings
from app.llm.cache import CachingLLM
from app.llm.factory import build_llm
from app.retrieval.factory import build_retriever
from app.schemas import TriageRequest
from app.triage.service import run_triage

APP_JS = Path("app/static/app.js")
# The answer shown as the placeholder of the clarification box, minus its "e.g. ".
SAMPLE_CLARIFICATION = "payments-api, about 7% of card payments failing since 20:10"


def sample_incidents(js: str) -> dict[str, str]:
    """``const NAME = `...`;`` or ``"..."`` literals ending in _INCIDENT, trimmed like the UI."""
    found = {}
    for name, tick, quoted in re.findall(
        r'const (\w+_INCIDENT) = (?:`([^`]*)`|"([^"]*)");', js
    ):
        found[name] = (tick or quoted).strip()
    return found


def main() -> int:
    base = get_settings()
    settings = base.model_copy(update={
        "llm_cache": True, "llm_cache_dir": base.demo_cache_dir, "demo_mode": False,
    })
    samples = sample_incidents(APP_JS.read_text(encoding="utf-8"))
    if not samples:
        print("error: no *_INCIDENT samples found in app.js", file=sys.stderr)
        return 2
    llm = build_llm(settings)
    retriever = build_retriever(settings)
    print(f"model={llm.model_name} thinking={settings.gemini_thinking_level} "
          f"retrieval={settings.retrieval_mode} k={settings.top_k} -> {settings.llm_cache_dir}")

    for name, incident in samples.items():
        for mode in ("no_retrieval", "rag", "agent"):
            req = TriageRequest(incident=incident, mode=mode)
            resp = run_triage(req, retriever=retriever, llm=llm, settings=settings)
            print(f"{name:<16} {mode:<13} {resp.status}")
            if resp.status == "needs_clarification":
                req = req.model_copy(update={"clarification": SAMPLE_CLARIFICATION})
                resp = run_triage(req, retriever=retriever, llm=llm, settings=settings)
                print(f"{name:<16} {mode:<13} + clarification -> {resp.status}")
    if isinstance(llm, CachingLLM):
        print(f"cache: {llm.misses} new answers, {llm.hits} already cached")
    return 0


if __name__ == "__main__":
    sys.exit(main())
