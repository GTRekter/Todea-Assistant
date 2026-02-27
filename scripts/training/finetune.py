"""
finetune.py — Fine-tune llama3.1:8b on Linkerd training data.

Device support:
  CUDA  → 4-bit quantization (bitsandbytes), best performance
  MPS   → fp16, no quantization (Apple Silicon, ~16 GB unified memory needed)
  CPU   → fp32, no quantization (very slow — hours per epoch)

Requirements:
    pip install torch transformers peft trl accelerate datasets
    # CUDA only (optional, for 4-bit + adamw_8bit):
    pip install bitsandbytes

HuggingFace access:
    The default model requires accepting the Llama 3.1 license on HuggingFace.
    Then run: huggingface-cli login

Usage:
    python finetune.py
    python finetune.py --model meta-llama/Meta-Llama-3.1-8B-Instruct
    python finetune.py --data data/training_data.jsonl --epochs 3
    python finetune.py --model meta-llama/Meta-Llama-3.2-3B-Instruct  # smaller, faster on Mac
"""

import argparse
import os

import torch
from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
)
from trl import SFTConfig, SFTTrainer

# ─── Device detection ─────────────────────────────────────────────────────────

def get_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if torch.backends.mps.is_available():
        return "mps"
    return "cpu"


# ─── Defaults ─────────────────────────────────────────────────────────────────

DEFAULT_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct"
MAX_SEQ_LENGTH = 2048


# ─── Args ─────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fine-tune a Llama model on Linkerd training data"
    )
    p.add_argument("--model", default=DEFAULT_MODEL,
                   help="HuggingFace model ID (default: %(default)s)")
    p.add_argument("--data", default="data/training_data.jsonl",
                   help="Path to ShareGPT-format JSONL training data")
    p.add_argument("--output", default="output",
                   help="Output directory for checkpoints and adapter")
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=None,
                   help="Per-device batch size (auto-detected if not set)")
    p.add_argument("--lora-rank", type=int, default=16,
                   help="LoRA rank — increase for more capacity, uses more memory")
    return p.parse_args()


# ─── Data formatting ──────────────────────────────────────────────────────────

def format_conversation(example: dict) -> dict:
    """Convert ShareGPT format → single text string for SFT."""
    text = ""
    for turn in example.get("conversations", []):
        role = turn.get("from", "")
        value = turn.get("value", "")
        if role == "system":
            text += f"<|system|>\n{value}\n"
        elif role == "human":
            text += f"<|user|>\n{value}\n"
        elif role == "gpt":
            text += f"<|assistant|>\n{value}\n"
    return {"text": text}


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    args = parse_args()
    device = get_device()
    print(f"Device : {device.upper()}")
    print(f"Model  : {args.model}")
    print(f"Data   : {args.data}")

    # ── Load tokenizer ────────────────────────────────────────────────────────
    tokenizer = AutoTokenizer.from_pretrained(args.model)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── Load model ────────────────────────────────────────────────────────────
    if device == "cuda":
        try:
            from transformers import BitsAndBytesConfig
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_compute_dtype=torch.bfloat16,
                bnb_4bit_use_double_quant=True,
            )
            model = AutoModelForCausalLM.from_pretrained(
                args.model,
                quantization_config=bnb_config,
                device_map="auto",
            )
            print("Loaded in 4-bit (CUDA)")
        except ImportError:
            # bitsandbytes not installed — fall back to bf16
            model = AutoModelForCausalLM.from_pretrained(
                args.model,
                dtype=torch.bfloat16,
                device_map="auto",
            )
            print("Loaded in bf16 (CUDA, bitsandbytes not found)")

    elif device == "mps":
        # device_map is not supported with MPS; load then move
        print("Loading model in fp16 (MPS) — requires ~16 GB unified memory ...")
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            dtype=torch.float16,
        )
        model = model.to("mps")

    else:
        print("Loading model in fp32 (CPU) — this will be very slow ...")
        model = AutoModelForCausalLM.from_pretrained(
            args.model,
            dtype=torch.float32,
        )

    # ── LoRA adapter ──────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_rank,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Dataset ───────────────────────────────────────────────────────────────
    dataset = load_dataset("json", data_files=args.data, split="train")
    dataset = dataset.map(format_conversation, remove_columns=dataset.column_names)
    print(f"Training examples: {len(dataset)}")

    # ── Training args ─────────────────────────────────────────────────────────
    # On MPS/CPU use smaller batches and compensate with gradient accumulation
    batch_size = args.batch_size or (2 if device == "cuda" else 1)
    grad_accum = 4 if device == "cuda" else 8

    training_args = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        warmup_steps=10,
        learning_rate=2e-4,
        # Mixed precision — not supported on MPS, skip on CPU
        fp16=(device == "cuda" and not torch.cuda.is_bf16_supported()),
        bf16=(device == "cuda" and torch.cuda.is_bf16_supported()),
        logging_steps=10,
        save_strategy="epoch",
        # adamw_8bit requires bitsandbytes (CUDA only)
        optim="adamw_8bit" if device == "cuda" else "adamw_torch",
        dataloader_pin_memory=(device == "cuda"),
        report_to="none",
        dataset_text_field="text",
        max_length=MAX_SEQ_LENGTH,
    )

    # ── Train ─────────────────────────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=dataset,
        args=training_args,
    )

    print("\nStarting training ...")
    trainer.train()

    # ── Save adapter ──────────────────────────────────────────────────────────
    adapter_dir = os.path.join(args.output, "lora-adapter")
    model.save_pretrained(adapter_dir)
    tokenizer.save_pretrained(adapter_dir)
    print(f"\nAdapter saved to {adapter_dir}/")
    print("\nNext: merge adapter and convert to GGUF with llama.cpp:")
    print(f"  python llama.cpp/convert_hf_to_gguf.py {adapter_dir} --outtype q4_k_m")


if __name__ == "__main__":
    main()
