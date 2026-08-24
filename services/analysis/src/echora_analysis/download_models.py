from huggingface_hub import snapshot_download

MODELS = (
    ("OpenMuQ/MuQ-MuLan-large", "2e01c796b71dca71b45251384c04cd7b237c9020"),
    ("OpenMuQ/MuQ-large-msd-iter", "0562a57814f6f8bbd9fdea0a25921a2fce1a841a"),
    ("FacebookAI/xlm-roberta-base", "e73636d4f797dec63c3081bb6ed5c7b0bb3f2089"),
    ("m-a-p/MERT-v1-95M", "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5"),
    ("BAAI/bge-m3", "5617a9f61b028005a4858fdac845db406aefb181"),
)


def main() -> None:
    for model, revision in MODELS:
        print(f"Downloading {model}@{revision}", flush=True)
        snapshot_download(repo_id=model, revision=revision)
    print("All model snapshots are available.", flush=True)


if __name__ == "__main__":
    main()
