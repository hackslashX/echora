import hashlib
import os
from pathlib import Path
import urllib.request

import torch
from demucs import pretrained
from huggingface_hub import snapshot_download

from .melody_config import MELODY_DEMUCS_MODEL

ESSENTIA_MODELS = (
    ("https://essentia.upf.edu/models/feature-extractors/discogs-effnet/discogs-effnet-bsdynamic-1.onnx",
     "a280825b334797cf677939db8cd5762c0392aedd0ca6415dbc1cd083f045e43c"),
    ("https://essentia.upf.edu/models/classification-heads/gender/gender-discogs-effnet-1.onnx",
     "e3e865d4bf36d4817f32ddab9452b2729f9e33a4d068d1c44ea44972a7999e91"),
    ("https://essentia.upf.edu/models/classification-heads/voice_instrumental/voice_instrumental-discogs-effnet-1.onnx",
     "20155e4c439714b0c45c08644b73c8e12d9dccb173bd4ab9934bf1e5aee837ca"),
)

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


def _download_essentia() -> None:
    """Fetch the MTG-Jamendo voice/gender classifier files used by voice_pipeline."""
    directory = Path(os.environ.get("ESSENTIA_MODELS_DIR", "/data/models/essentia"))
    directory.mkdir(parents=True, exist_ok=True)
    for url, expected_sha256 in ESSENTIA_MODELS:
        target = directory / url.rsplit("/", 1)[-1]
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == expected_sha256:
            print(f"essentia model {target.name} is available.", flush=True)
            continue
        print(f"Downloading {url} into {directory}", flush=True)
        partial = target.with_suffix(target.suffix + ".part")
        urllib.request.urlretrieve(url, partial)
        actual_sha256 = hashlib.sha256(partial.read_bytes()).hexdigest()
        if actual_sha256 != expected_sha256:
            partial.unlink(missing_ok=True)
            raise ValueError(f"Checksum mismatch for {target.name}: {actual_sha256}")
        partial.replace(target)
        print(f"essentia model {target.name} is available.", flush=True)


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
    _download_essentia()
    print("All model snapshots are available.", flush=True)


if __name__ == "__main__":
    main()
