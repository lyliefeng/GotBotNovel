"""Download an embedding model into a flat, symlink-free directory for desktop bundles."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from huggingface_hub import snapshot_download


def replace_symlinks(root: Path) -> None:
    """Replace any links left by the Hub cache with regular files/directories."""
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        if not path.is_symlink():
            continue
        target = path.resolve(strict=True)
        path.unlink()
        if target.is_dir():
            shutil.copytree(target, path)
        else:
            shutil.copy2(target, path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        shutil.rmtree(args.output)

    snapshot_download(
        args.model,
        local_dir=args.output,
        local_dir_use_symlinks=False,
    )

    # local_dir may contain Hub bookkeeping that is not needed at runtime.
    shutil.rmtree(args.output / ".cache", ignore_errors=True)
    replace_symlinks(args.output)

    files = [path for path in args.output.rglob("*") if path.is_file()]
    if not files:
        raise RuntimeError(f"No model files downloaded to {args.output}")
    if any(path.is_symlink() for path in args.output.rglob("*")):
        raise RuntimeError(f"Model directory still contains symlinks: {args.output}")
    print(f"Downloaded {len(files)} model files to {args.output}")


if __name__ == "__main__":
    main()
