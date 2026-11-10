"""QLoRA fine-tuning of a small instruct model as a severity classifier.

    python -m finetune.train_qlora                       # on a CUDA GPU (Colab T4)
    python -m finetune.train_qlora --no-4bit --max-steps 2 --limit 16 \\
        --base Qwen/Qwen2.5-0.5B-Instruct                # CPU smoke test of the loop

**QLoRA:** the base model is loaded frozen in 4-bit NF4 with double quantisation, and
LoRA adapters (r=16, alpha=32, dropout 0.05) are trained on every attention and MLP
projection, in fp16 (T4s have no bf16). Only the adapters are saved, a few dozen MB.

**Completion-only loss.** The prompt tokens are masked (label -100). The loss is only on
the answer, ``SEV2<|im_end|>``. The model learns to answer, not to reproduce the policy.

**Model selection** uses validation loss, measured each epoch, and keeps the best epoch.
The test split is never touched here.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from finetune.common import DEFAULT_BASE, chat_prompt, load_split

DATA = Path("finetune/data")
OUT = Path("finetune/outputs/adapter")
TARGETS = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def encode(tokenizer: Any, row: dict[str, Any], max_len: int) -> dict[str, list[int]]:
    """Prompt tokens masked out; loss on the label and the end-of-turn token only."""
    prompt_ids = tokenizer(chat_prompt(tokenizer, row["prompt"]),
                           add_special_tokens=False)["input_ids"]
    answer_ids = tokenizer(row["label"], add_special_tokens=False)["input_ids"]
    answer_ids = answer_ids + [tokenizer.convert_tokens_to_ids("<|im_end|>")
                               if "<|im_end|>" in tokenizer.get_vocab() else tokenizer.eos_token_id]
    prompt_ids = prompt_ids[-(max_len - len(answer_ids)):]  # keep the end: the incident
    return {"input_ids": prompt_ids + answer_ids,
            "attention_mask": [1] * (len(prompt_ids) + len(answer_ids)),
            "labels": [-100] * len(prompt_ids) + answer_ids}


def collate(pad_id: int):
    import torch

    def fn(batch: list[dict[str, list[int]]]) -> dict[str, Any]:
        n = max(len(b["input_ids"]) for b in batch)
        out = {k: [] for k in ("input_ids", "attention_mask", "labels")}
        for b in batch:
            pad = n - len(b["input_ids"])
            out["input_ids"].append(b["input_ids"] + [pad_id] * pad)
            out["attention_mask"].append(b["attention_mask"] + [0] * pad)
            out["labels"].append(b["labels"] + [-100] * pad)
        return {k: torch.tensor(v) for k, v in out.items()}
    return fn


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m finetune.train_qlora")
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--data", type=Path, default=DATA)
    p.add_argument("--out", type=Path, default=OUT)
    p.add_argument("--epochs", type=float, default=2)
    p.add_argument("--lr", type=float, default=2e-4)
    p.add_argument("--rank", type=int, default=16)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--grad-accum", type=int, default=2)
    p.add_argument("--max-len", type=int, default=768)
    p.add_argument("--max-steps", type=int, default=-1)
    p.add_argument("--limit", type=int, default=None, help="use the first N rows (smoke test)")
    p.add_argument("--no-4bit", action="store_true", help="plain LoRA, e.g. on CPU")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args(argv)

    import torch
    from datasets import Dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
        set_seed,
    )

    set_seed(args.seed)
    cuda = torch.cuda.is_available()
    quantize = not args.no_4bit
    if quantize and not cuda:
        raise SystemExit("4-bit QLoRA needs a CUDA GPU (bitsandbytes). Use --no-4bit on CPU.")
    tok = AutoTokenizer.from_pretrained(args.base)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else tok.eos_token_id

    kwargs: dict[str, Any] = {}
    if quantize:
        from transformers import BitsAndBytesConfig
        kwargs["quantization_config"] = BitsAndBytesConfig(
            load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.float16)
        kwargs["device_map"] = {"": 0}
    else:
        kwargs["torch_dtype"] = torch.float32
    model = AutoModelForCausalLM.from_pretrained(args.base, **kwargs)
    if quantize:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model = get_peft_model(model, LoraConfig(r=args.rank, lora_alpha=2 * args.rank,
                                             lora_dropout=0.05, target_modules=TARGETS,
                                             task_type="CAUSAL_LM"))
    trainable, total = model.get_nb_trainable_parameters()
    print(f"trainable params: {trainable:,} of {total:,} ({trainable / total:.2%})")

    def ds(split: str) -> Dataset:
        rows = load_split(args.data / f"{split}.jsonl", args.limit)
        return Dataset.from_list([encode(tok, r, args.max_len) for r in rows])

    train, val = ds("train"), ds("val")
    targs = TrainingArguments(
        output_dir=str(args.out.parent / "checkpoints"), num_train_epochs=args.epochs,
        max_steps=args.max_steps, learning_rate=args.lr, lr_scheduler_type="cosine",
        warmup_ratio=0.05, per_device_train_batch_size=args.batch // args.grad_accum,
        per_device_eval_batch_size=args.batch, gradient_accumulation_steps=args.grad_accum,
        eval_strategy="epoch" if args.max_steps < 0 else "no",
        save_strategy="epoch" if args.max_steps < 0 else "no",
        load_best_model_at_end=args.max_steps < 0, metric_for_best_model="eval_loss",
        save_total_limit=2, logging_steps=10, fp16=cuda, report_to=[], seed=args.seed,
        remove_unused_columns=False, use_cpu=not cuda,
    )
    trainer = Trainer(model=model, args=targs, train_dataset=train, eval_dataset=val,
                      data_collator=collate(pad_id))
    t0 = time.time()
    trainer.train()
    minutes = (time.time() - t0) / 60
    metrics = trainer.evaluate() if len(val) else {}
    args.out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(args.out)
    tok.save_pretrained(args.out)
    meta = {"base": args.base, "quantized_4bit": quantize, "rank": args.rank, "lr": args.lr,
            "epochs": args.epochs, "train_rows": len(train), "val_rows": len(val),
            "train_minutes": round(minutes, 1), "val_loss": metrics.get("eval_loss"),
            "gpu": torch.cuda.get_device_name(0) if cuda else "cpu",
            "trainable_params": trainable}
    (args.out / "training_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8",
                                                 newline="\n")
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
