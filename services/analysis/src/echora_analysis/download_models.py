from pathlib import Path

from huggingface_hub import snapshot_download

MODELS = (
    ("OpenMuQ/MuQ-MuLan-large", "2e01c796b71dca71b45251384c04cd7b237c9020", False),
    ("OpenMuQ/MuQ-large-msd-iter", "0562a57814f6f8bbd9fdea0a25921a2fce1a841a", True),
    ("xlm-roberta-base", "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089", True),
    ("m-a-p/MERT-v1-95M", "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5", False),
    ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181", False),
)


def _pin_main_ref(snapshot_path: str) -> None:
    snapshot = Path(snapshot_path)
    refs = snapshot.parent.parent / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "main").write_text(snapshot.name, encoding="utf-8")


def main() -> None:
    for model, revision, needs_main_ref in MODELS:
        print(f"Downloading {model}@{revision}", flush=True)
        snapshot = snapshot_download(repo_id=model, revision=revision)
        if needs_main_ref:
            # MuQ constructs these dependencies without forwarding a revision.
            # Point their local `main` refs at the reviewed commits so offline
            # inference remains pinned.
            _pin_main_ref(snapshot)
    print("All model snapshots are available.", flush=True)


if __name__ == "__main__":
    main()
