import os

from huggingface_hub import snapshot_download
from huggingface_hub.utils import disable_progress_bars

default_model_path = '~/.cache/huggingface/hub/'
model_path = os.path.expanduser(default_model_path);

disable_progress_bars()

models = [
    ['ds4sd/CodeFormula', 'v1.0.2'],
    ['ds4sd/DocumentFigureClassifier', 'v1.0.1'],
    ['ds4sd/docling-models', 'v2.2.0'],
    ['sentence-transformers/all-MiniLM-L6-v2', None],
]

for model, revision in models:
    print(f"Downloading model {model}:{revision} to {model_path}")
    snapshot_download(
        repo_id=model,
        force_download=True,
        local_dir=model_path,
        revision=revision,
    )

print("Done.")
