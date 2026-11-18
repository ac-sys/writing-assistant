"""Pre-download the local model(s) so the app works offline afterwards.
Usage: python download_model.py            (default 0.5B ultra-fast model)
       python download_model.py --quality  (1.5B quality model)
       python download_model.py --tiny     (360M featherweight model)
       python download_model.py --all"""
import sys
from huggingface_hub import snapshot_download

models = {
    "fast": "Qwen/Qwen2.5-0.5B-Instruct",
    "quality": "Qwen/Qwen2.5-1.5B-Instruct",
    "tiny": "HuggingFaceTB/SmolLM2-360M-Instruct",
}
if "--all" in sys.argv:
    pick = list(models.values())
elif "--quality" in sys.argv:
    pick = [models["quality"]]
elif "--tiny" in sys.argv:
    pick = [models["tiny"]]
else:
    pick = [models["fast"]]

for m in pick:
    print("Downloading", m, "...")
    print(" ->", snapshot_download(m, allow_patterns=["*.json", "*.safetensors", "*.txt", "tokenizer*", "merges.txt", "vocab.json"]))
print("Done. The app now works without internet.")
