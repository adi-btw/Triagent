"""Pieces shared by training and evaluation, so both see byte-identical prompts.

Torch and transformers are imported lazily. The dataset builder and the tests that
check the prompt format then run in the app's environment, which has no ML stack.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LABELS = ("SEV1", "SEV2", "SEV3", "SEV4")
DEFAULT_BASE = "Qwen/Qwen2.5-1.5B-Instruct"  # Apache-2.0, fits a free T4 in 4-bit easily


def load_split(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    rows = [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x]
    return rows[:limit] if limit else rows


def chat_prompt(tokenizer: Any, prompt: str) -> str:
    """The user turn in the model's own chat format, ending where the answer starts."""
    return tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                         tokenize=False, add_generation_prompt=True)


def label_token_ids(tokenizer: Any) -> tuple[list[int], list[list[int]]]:
    """Split the four labels into a shared token prefix and per-label remainders.

    For tokenizers that write ``SEV1`` as ``SE`` ``V`` ``1``, the labels share a prefix and
    differ in one token. Scoring is then one forward pass over prompt + prefix, reading
    four logits. Otherwise each remainder is scored as a full continuation.
    """
    ids = [tokenizer(label, add_special_tokens=False)["input_ids"] for label in LABELS]
    n = 0
    while all(len(x) > n for x in ids) and len({x[n] for x in ids}) == 1:
        n += 1
    return ids[0][:n], [x[n:] for x in ids]


def score_labels(model: Any, tokenizer: Any, prompt: str) -> dict[str, float]:
    """Log-probability of each label as the answer. Constrained: only the 4 labels exist."""
    import torch

    prefix, rest = label_token_ids(tokenizer)
    base = tokenizer(chat_prompt(tokenizer, prompt), add_special_tokens=False)["input_ids"]
    device = next(model.parameters()).device
    with torch.no_grad():
        if all(len(r) == 1 for r in rest):
            x = torch.tensor([base + prefix], device=device)
            logits = model(x).logits[0, -1].float()
            logp = torch.log_softmax(logits, dim=-1)
            return {lab: float(logp[r[0]]) for lab, r in zip(LABELS, rest, strict=True)}
        scores = {}
        for lab, r in zip(LABELS, rest, strict=True):
            seq = base + prefix + r
            x = torch.tensor([seq], device=device)
            logp = torch.log_softmax(model(x).logits[0].float(), dim=-1)
            start = len(base) + len(prefix)
            scores[lab] = float(sum(logp[start - 1 + i, tok] for i, tok in enumerate(r)))
        return scores
