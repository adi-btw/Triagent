# Stage 4 (optional): QLoRA fine-tuning for severity classification

**Status: planned.** This document defines the experiment, its data and hardware requirements, and
the go/no-go criteria that must hold before any training code is written.

## Where QLoRA fits in this project

| Technique | Changes | Good for here | Bad for here |
|---|---|---|---|
| RAG (stages 1–2) | What the model *sees* at question time | Causes and next steps, which depend on runbooks that change weekly | — |
| Prompting with the policy | What the model is *told* | Severity, since POL-SEV-001 is a short, explicit rubric | Costs tokens on every call; depends on the hosted model |
| Fine-tuning (QLoRA) | What the model *does by default* | A narrow, stable behavior: mapping incident facts to SEV1–4 | Knowledge that changes (retrain every time a runbook changes) |

The guiding rule: **use RAG for knowledge that changes and fine-tuning for behavior that
doesn't.** Severity classification is a stable behavior with a fixed label set. That makes it a fair
fine-tuning target, while "know our runbooks" is not.

**What QLoRA is:** the base model's weights are loaded *frozen* in 4-bit (NF4) precision. Small
low-rank adapter matrices (LoRA, rank about 8–64, roughly 0.1–1% of the parameters) are trained in
16-bit on top of them. Memory drops by about 4x compared with 16-bit LoRA, which is why a
1–8B model can train on one consumer or free cloud GPU. The source is Dettmers et al., *QLoRA*, 2023.

## The question the experiment answers

> On the same held-out incidents, does a small open-weight model *after* QLoRA classify severity
> better than the *same* model before fine-tuning, given the same prompt?

The control has to be the same base model with the same prompt, zero-shot. Comparing a fine-tuned 1.5B model with Gemini
tells you about model size, not about fine-tuning. Report Gemini's stage-3 severity accuracy as a reference line.

**Be honest about the likely outcome.** The severity rubric is explicit, so a capable prompted model may already
be near the ceiling. The realistic wins are a **small, cheap, offline** classifier that matches a
large model, and **consistency**, meaning fewer off-by-one errors on borderline cases. A null result is still a valid
result; write it up.

## Dataset requirements

The current 32 eval cases are **not enough and must not be used for training**. They are the stage-3
test set, and training on them would leak the test set into the model.

| Split | Size (minimum → comfortable) | Purpose |
|---|---|---|
| Train | 400 → 1,000 examples (≥100 per class) | Fit the adapters |
| Validation | 80 → 150 | Early stopping and choosing the LoRA rank / learning rate |
| Held-out test | 200 (50 per class) | The only numbers you report |

Why 200 test cases: at about 80% accuracy with n=200, the 95% interval is about ±5.5 points. With n=32 it is about ±14 points,
which is too wide to detect any realistic fine-tuning gain.

**Where the labels come from, best first:**
1. **Hand-written plus a rubric check.** Write incident templates per scenario and vary service, error
   rate, latency multiple and wording. Label each one with `POL-SEV-001` and have a script check the rule.
   It's slow, but the labels are clean.
2. **LLM-generated, then human-reviewed.** Ask a strong model for incidents *and* labels, then
   review a random 20%, and more if disagreement is above 5%. It's fast, but the model can learn the generator's
   phrasing instead of the rubric.
3. **Public postmortems** (for example, collections of published outage write-ups) as a realism
   check for the test set only, re-labeled under POL-SEV-001.

**Leakage rules.** Split by *scenario template*, not by row, so paraphrases of one incident
never land in both train and test. Remove near-duplicates by text similarity. Balance the classes, or
report macro-F1 alongside accuracy.

**Example format** (instruction tuning; compute the loss on the completion only):
```json
{"prompt": "<severity policy text>\n\nIncident:\n<incident>\n\nSeverity (SEV1-SEV4):", "completion": " SEV2"}
```

## Hardware requirements

This machine has **no NVIDIA GPU**, and QLoRA's 4-bit kernels (`bitsandbytes`) need CUDA. So training
runs in the cloud. Inference with the trained adapter can then run on a CPU.

| Base model size (examples) | 4-bit weights | Training memory (seq 512, batch 4–8) | Where to run it | Time for ~1k examples × 3 epochs |
|---|---|---|---|---|
| 0.5–2B (Qwen2.5-1.5B-Instruct, Llama-3.2-1B-Instruct, Gemma-class 1B) | ~1–1.5 GB | ~5–8 GB | Free Colab T4 (16 GB) or Kaggle T4/P100 | ~10–25 min |
| 3–4B (Llama-3.2-3B, Phi-mini class) | ~2–3 GB | ~8–12 GB | Colab T4 (tight) or L4 | ~25–50 min |
| 7–8B | ~5 GB | ~12–18 GB | L4 / A10G 24 GB (paid, about $0.5–1.5/hr) | ~1–2 h |

**Recommendation: start with a 1–2B instruct model on a free Colab T4.** It's cheap to repeat, and
the effect of fine-tuning is easiest to see on a model that starts out weak. Pick whichever current small
instruct model has a permissive license when you start. The names above are examples.

**Software stack:** `transformers`, `peft`, `bitsandbytes`, `trl` (SFTTrainer), `datasets`, and
`accelerate`. Pin the versions in a separate `finetune/requirements.txt`, so the main app never depends
on CUDA.

## What would get built (if you go ahead)

```
finetune/
├── build_dataset.py     # templates → train/val/test JSONL, split by template, label checks
├── train_qlora.py       # 4-bit NF4 base + LoRA (r=16, alpha=32, dropout 0.05), completion-only loss
├── evaluate.py          # base vs fine-tuned on test.jsonl: accuracy, macro-F1, within-one, confusion,
│                        #   bootstrap CIs, invalid-label rate, latency per example
└── colab_train.ipynb    # thin wrapper that runs the scripts on a T4
```

The evaluation uses **constrained decoding or log-prob scoring** over the 4 labels, so neither model
can produce an invalid label and the comparison stays fair.

## Go/no-go criteria

Proceed only if all of these hold:
- [ ] At least ~600 labeled examples (train + validation + test), with a hand-reviewed sample.
- [ ] A CUDA GPU is available (Colab or Kaggle is sufficient).
- [ ] Stage-3 results show severity errors worth fixing, or a small offline classifier is needed.
- [ ] The result is reported even if fine-tuning doesn't help.

### Design FAQ
1. *Why QLoRA rather than full fine-tuning?* Memory. A frozen 4-bit base plus adapters trains a 7B model on one
   24 GB GPU, while full fine-tuning would need several 80 GB GPUs. The quality is close to 16-bit LoRA on most tasks.
2. *Why not fine-tune the runbooks into the model?* They change. RAG updates as soon as you re-ingest and
   gives citations you can check. A fine-tuned model can't cite its sources and goes stale.
3. *How did you stop the test set leaking into training?* Split by scenario template, remove near-duplicates, and
   never train on the stage-3 eval cases.
4. *What's the control?* The same base model and prompt with no adapters, on the same held-out set.
5. *Why can't the classifier output an invalid label?* Decoding is constrained to the 4 labels, or the labels are ranked by log-probability.
