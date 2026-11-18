"""Pre-download the local model(s) so the app works offline afterwards.
Usage: python download_model.py            (default 1.5B quality model)
       python download_model.py --fast     (0.5B fast model)
       python download_model.py --all"""
import sys
from huggingface_hub import snapshot_download

models = {"quality": "Qwen/Qwen2.5-1.5B-Instruct", "fast": "Qwen/Qwen2.5-0.5B-Instruct"}
pick = list(models.values()) if "--all" in sys.argv else [models["fast" if "--fast" in sys.argv else "quality"]]
for m in pick:
    print("Downloading", m, "...")
    print(" ->", snapshot_download(m, allow_patterns=["*.json", "*.safetensors", "*.txt", "tokenizer*", "merges.txt", "vocab.json"]))
print("Done. The app now works without internet.")
