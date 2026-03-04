"""
train.py — Wrapper for finetune.py called by the training-hub Kubernetes Job.

Called by training-hub as a Kubernetes Job:
    python training/train.py --model=meta-llama/Meta-Llama-3.1-8B-Instruct \
                             --adapter-name=my-adapter

Delegates to finetune.py with paths resolved against the /data PVC mount.
"""

import argparse
import subprocess
import sys
from pathlib import Path

DATA_DIR = Path("/data")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Todea fine-tuning job")
    parser.add_argument("--model",        default="meta-llama/Meta-Llama-3.1-8B-Instruct")
    parser.add_argument("--adapter-name", default="adapter", dest="adapter_name")
    args = parser.parse_args()

    output_dir = DATA_DIR / "adapters" / args.adapter_name
    data_path  = DATA_DIR / "training_data.jsonl"

    cmd = [
        sys.executable, "training/finetune.py",
        f"--model={args.model}",
        f"--output={output_dir}",
        f"--data={data_path}",
    ]

    print(f">>> {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
