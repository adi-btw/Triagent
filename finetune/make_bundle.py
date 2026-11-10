"""Zip what Colab needs into one file to upload: code, data and pinned requirements.

    python -m finetune.make_bundle    # -> finetune/outputs/triagent_finetune.zip

The repository is private, so a notebook can't clone it without a token. Uploading one
zip is simpler, and it keeps tokens out of the notebook.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

FILES = ["finetune/__init__.py", "finetune/common.py", "finetune/build_dataset.py",
         "finetune/train_qlora.py", "finetune/evaluate.py", "finetune/requirements.txt",
         "finetune/data/train.jsonl", "finetune/data/val.jsonl", "finetune/data/test.jsonl",
         "finetune/data/stats.json"]
OUT = Path("finetune/outputs/triagent_finetune.zip")


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for f in FILES:
            z.write(f, f)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB): upload it in the notebook's step 2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
