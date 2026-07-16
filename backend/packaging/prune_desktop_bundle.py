"""Remove non-runtime PyTorch payload from a PyInstaller desktop bundle."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


GPU_MARKERS = (
    "cublas",
    "cudnn",
    "cufft",
    "cuda",
    "curand",
    "cusolver",
    "cusparse",
    "nccl",
    "nvjitlink",
    "nvrtc",
    "nvshmem",
    "nvtx",
    "torch_cuda",
)

REMOVABLE_DIRS = {
    "include",
    "testing",
    "test",
    "tests",
    "torchgen",
    "_inductor",
    "distributed",
}


def should_remove(path: Path) -> bool:
    name = path.name.lower()
    if any(marker in name for marker in GPU_MARKERS):
        return True
    if path.suffix.lower() in {".pyi", ".h", ".hpp"}:
        return True
    return False


def prune(root: Path) -> tuple[int, int]:
    removed_files = 0
    removed_bytes = 0

    # These directories are development/optional accelerator payloads and are
    # not needed by SentenceTransformer(..., device="cpu").
    for directory in root.rglob("*"):
        if directory.is_dir() and directory.name in REMOVABLE_DIRS:
            size = sum(item.stat().st_size for item in directory.rglob("*") if item.is_file())
            shutil.rmtree(directory, ignore_errors=True)
            removed_files += 1
            removed_bytes += size

    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file() and should_remove(path):
            removed_bytes += path.stat().st_size
            path.unlink()
            removed_files += 1

    return removed_files, removed_bytes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    args = parser.parse_args()
    root = args.bundle.resolve()
    if not root.is_dir():
        raise SystemExit(f"Bundle directory does not exist: {root}")
    removed_files, removed_bytes = prune(root)
    remaining_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    print(
        f"Pruned {removed_files} entries / {removed_bytes / 1024 / 1024:.1f} MiB; "
        f"remaining bundle size {remaining_bytes / 1024 / 1024:.1f} MiB"
    )


if __name__ == "__main__":
    main()
