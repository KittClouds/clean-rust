import argparse
from pathlib import Path

from huggingface_hub import hf_hub_download


DEFAULT_REPO = "knowledgator/gliner-linker-base-v1.0"
DEFAULT_FILES = (
    ".gitattributes",
    "README.md",
    "added_tokens.json",
    "gliner_config.json",
    "merges.txt",
    "pytorch_model.bin",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)


def main():
    parser = argparse.ArgumentParser(description="Download GLiNER-Linker assets to a local folder.")
    parser.add_argument("--repo", default=DEFAULT_REPO)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in DEFAULT_FILES:
        print(f"download {name}", flush=True)
        path = Path(
            hf_hub_download(
                args.repo,
                filename=name,
                local_dir=str(out_dir),
                cache_dir=args.cache_dir,
            )
        )
        print(f"done {name} {path.stat().st_size}", flush=True)
    print("done all", flush=True)


if __name__ == "__main__":
    main()
