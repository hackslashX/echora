import os
from pathlib import Path

import torch
from demucs import pretrained
from huggingface_hub import snapshot_download

from .melody_config import MELODY_DEMUCS_MODEL

MODELS = (
    ("OpenMuQ/MuQ-MuLan-large", "2e01c796b71dca71b45251384c04cd7b237c9020", False),
    ("OpenMuQ/MuQ-large-msd-iter", "0562a57814f6f8bbd9fdea0a25921a2fce1a841a", True),
    ("xlm-roberta-base", "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089", True),
    ("m-a-p/MERT-v1-95M", "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5", False),
    ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", False),
    ("NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn", "2ab2b5f46539ee284703c281f286b01d2410ee12", False),
)


def _pin_main_ref(snapshot_path: str) -> None:
    snapshot = Path(snapshot_path)
    refs = snapshot.parent.parent / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(snapshot.name, encoding="utf-8")


def _download_demucs() -> None:
    """Preload required separators, then remove known checkpoints no longer used."""
    required_models = {MELODY_DEMUCS_MODEL}
    if os.environ.get("FA_KARA_VOCAL_SEPARATION", "false").lower() == "true":
        karaoke_model = os.environ.get("FA_KARA_DEMUCS_MODEL", "htdemucs_ft").strip()
        if karaoke_model not in {"htdemucs", "htdemucs_ft"}:
            raise ValueError("FA_KARA_DEMUCS_MODEL must be 'htdemucs' or 'htdemucs_ft'")
        required_models.add(karaoke_model)
    torch_home = Path(os.environ.get("TORCH_HOME", "/models/torch"))
    torch_home.mkdir(parents=True, exist_ok=True)
    os.environ["TORCH_HOME"] = str(torch_home)
    for model_name in sorted(required_models):
        print(f"Downloading demucs {model_name} checkpoints into TORCH_HOME", flush=True)
        pretrained.get_model(model_name)
        print(f"demucs {model_name} checkpoints are available.", flush=True)

    obsolete_checkpoints = {
        "htdemucs": ("955717e8-8726e21a.th",),
    }
    checkpoint_directory = torch_home / "hub" / "checkpoints"
    for model_name, filenames in obsolete_checkpoints.items():
        if model_name in required_models:
            continue
        for filename in filenames:
            checkpoint = checkpoint_directory / filename
            if checkpoint.exists():
                checkpoint.unlink()
                print(f"Removed unused demucs checkpoint {checkpoint}", flush=True)


def main() -> None:
    for model, revision, needs_main_ref in MODELS:
        print(f"Downloading {model}@{revision}", flush=True)
        snapshot = snapshot_download(repo_id=model, revision=revision)
        if needs_main_ref:
            # MuQ constructs these dependencies without forwarding a revision.
            # Point their local `main` refs at the reviewed commits so offline
            # inference remains pinned.
            _pin_main_ref(snapshot)
    _download_demucs()
    print("All model snapshots are available.", flush=True)


if __name__ == "__main__":
    main()
