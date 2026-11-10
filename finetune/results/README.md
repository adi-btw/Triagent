# QLoRA severity classifier: results

**Status: zero-shot baseline measured; QLoRA run pending on Colab.** After the Colab run,
`python -m finetune.evaluate compare` replaces this file with the side-by-side table.

## Baseline: Qwen2.5-1.5B-Instruct, zero-shot (`base-cpu.json`)

200 held-out incidents from 7 scenario templates never used in training, 50 per class.
Same prompt as training (instruction + POL-SEV-001 + incident), scored by constrained
log-probability over SEV1–SEV4. Run on CPU in fp32, 3.9 s per incident.

| Metric | Value |
|---|---|
| Accuracy [95% CI] | **28.0%** [22.0–34.5] (chance is 25%) |
| Macro-F1 | 0.16 |
| Within one level | 78.0% |
| Boundary cases (n=34) | 32.4% |
| Under-rated / over-rated | 93 / 51 |
| Predicted mix | SEV3 ×193, SEV1 ×7 |

| gold \ predicted | SEV1 | SEV2 | SEV3 | SEV4 |
|---|---|---|---|---|
| SEV1 | 6 | 0 | 44 | 0 |
| SEV2 | 1 | 0 | 49 | 0 |
| SEV3 | 0 | 0 | 50 | 0 |
| SEV4 | 0 | 0 | 50 | 0 |

**Reading it:** zero-shot, the small model hardly applies the rubric. It answers SEV3 for
almost everything. That's not a scoring artifact: greedy free-text generation gives the
same SEV3 on spot checks. So the experiment has room to show a gain. The question it
answers is whether 1,000 rubric-labelled examples teach a 1.5B model to read error rates,
latency multiples and revenue paths. For reference, hosted Gemini gets 79–93% exact
severity on the 32 stage-3 cases (a different, smaller set).
