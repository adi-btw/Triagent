# QLoRA severity classifier: results

Base model `Qwen/Qwen2.5-1.5B-Instruct`, the same prompt, 200 held-out test incidents from scenario templates never seen in training. Labels are computed from POL-SEV-001; both models are scored by constrained log-probability over SEV1–SEV4.

Accuracy change: **+60.5 points** (paired bootstrap 95% CI +52.5 to +68.5): **significant improvement**.

| | Base (zero-shot) | QLoRA |
|---|---|---|
| Accuracy [95% CI] | 28.0% [22.0%–34.5%] | 88.5% [84.0%–93.0%] |
| Macro-F1 | 0.156 | 0.886 |
| Within one level | 78.0% | 100.0% |
| Boundary cases (n=34) | 32.4% | 82.4% |
| Under-rated (said less severe) | 93 | 7 |
| Over-rated (said more severe) | 51 | 16 |
| F1 SEV1 / SEV2 / SEV3 / SEV4 | 0.21 / 0.00 / 0.41 / 0.00 | 0.97 / 0.82 / 0.81 / 0.95 |
| Latency per example (cuda / cuda) | 89 ms | 65 ms |

## Accuracy by test template

| Template | Base | QLoRA |
|---|---|---|
| autoscaler_stuck | 29.0% | 87.1% |
| cache_stampede | 42.9% | 78.6% |
| cert_expiry | 50.0% | 89.3% |
| pipeline_broken | 0.0% | 100.0% |
| public_bucket | 50.0% | 100.0% |
| queue_backlog | 36.4% | 93.9% |
| staging_down | 0.0% | 16.7% |

## Confusion matrix: Base (rows: gold, columns: predicted)

| | SEV1 | SEV2 | SEV3 | SEV4 |
|---|---|---|---|---|
| SEV1 | 6 | 0 | 44 | 0 |
| SEV2 | 1 | 0 | 49 | 0 |
| SEV3 | 0 | 0 | 50 | 0 |
| SEV4 | 0 | 0 | 50 | 0 |

## Confusion matrix: QLoRA (rows: gold, columns: predicted)

| | SEV1 | SEV2 | SEV3 | SEV4 |
|---|---|---|---|---|
| SEV1 | 50 | 0 | 0 | 0 |
| SEV2 | 3 | 40 | 7 | 0 |
| SEV3 | 0 | 8 | 42 | 0 |
| SEV4 | 0 | 0 | 5 | 45 |

## Training

| | |
|---|---|
| base | Qwen/Qwen2.5-1.5B-Instruct |
| quantized_4bit | True |
| rank | 16 |
| lr | 0.0002 |
| epochs | 2 |
| train_rows | 1000 |
| val_rows | 160 |
| train_minutes | 11.1 |
| val_loss | 0.16932369768619537 |
| gpu | Tesla T4 |
| trainable_params | 18464768 |

## Reading the result

- **Fine-tuning taught the rubric.** Zero-shot, the model answers SEV3 for 193 of 200
  incidents. After about 11 minutes of QLoRA on a free T4 (18.5M trainable parameters,
  1.18% of the model), it gets 88.5% exact, and every answer is within one level. SEV1
  and SEV4 are nearly perfect (F1 0.97 and 0.95).
- **What's left is the SEV2/SEV3 boundary on revenue paths.** Of the 23 errors, 15
  confuse SEV2 and SEV3 on checkout, payments or cart. Some are latency-driven SEV2s
  (errors below 5%, but p95 more than 3x baseline) called SEV3. Others are 3–4.8% error
  rates called SEV2. That's arithmetic the model has to do from two durations or a count,
  and the place to add training data next.
- **One unseen scenario transfers badly:** `staging_down` (a staging environment is down,
  production is fine) gets 1 of 6 right, called SEV3 instead of SEV4. No training template
  describes a non-production environment. Splitting by template makes gaps like this
  visible; a random row split would have hidden them.
- **Same model, same prompt, same scoring:** the GPU baseline's 200 predictions are
  identical to the CPU baseline in `base-cpu.json`. The control is reproducible.
- **Latency** is per example on the T4, scored with one forward pass each. The tuned
  model runs with its adapters merged, so it costs no more than the base. The 89 ms vs
  65 ms gap is warm-up and run-to-run variation, not a speed-up from fine-tuning.

**Provenance.** Trained and evaluated on a free Colab T4 with the code and data in this
folder. The dataset rebuilt on Colab matched `finetune/data/` byte for byte (SHA-256).
`base.json` and `qlora.json` are the files `finetune.evaluate` wrote on Colab, downloaded
unchanged. As a cross-check, the notebook also printed each model's predictions with a
SHA-256 (base `86e2c2058fda`, QLoRA `48220a85b45b`); the transcription matched both. The
training table comes from the notebook's printout of `training_meta.json`. The adapter
weights stayed on Colab; rerun `colab_train.ipynb` (about 15 minutes) to reproduce them.
