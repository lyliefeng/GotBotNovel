#!/usr/bin/env python3
"""把 Electron 更新文件切分为适合上传到 Gitee Release 的小附件。"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_CHUNK_SIZE = 45 * 1024 * 1024
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


def find_single(input_dir: Path, pattern: str, label: str) -> Path:
    matches = sorted(path for path in input_dir.glob(pattern) if path.is_file())
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "无"
        raise RuntimeError(f"{label} 应恰好匹配一个文件，实际为: {names}")
    return matches[0]


def split_artifact(source: Path, output_dir: Path, chunk_size: int) -> dict[str, Any]:
    full_hash = hashlib.sha512()
    parts: list[dict[str, Any]] = []
    total_size = 0

    with source.open("rb") as source_handle:
        index = 0
        while True:
            chunk = source_handle.read(chunk_size)
            if not chunk:
                break
            full_hash.update(chunk)
            total_size += len(chunk)
            part_name = f"{source.name}.part{index:03d}"
            part_path = output_dir / part_name
            part_path.write_bytes(chunk)
            parts.append(
                {
                    "name": part_name,
                    "size": len(chunk),
                    "sha256": hashlib.sha256(chunk).hexdigest(),
                }
            )
            index += 1

    if total_size != source.stat().st_size:
        raise RuntimeError(f"读取文件大小发生变化: {source}")
    return {
        "filename": source.name,
        "size": total_size,
        "sha512": base64.b64encode(full_hash.digest()).decode("ascii"),
        "parts": parts,
    }


def prepare(input_dir: Path, output_dir: Path, version: str, chunk_size: int) -> dict[str, Any]:
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"版本号不是有效的发布版本: {version}")
    if chunk_size <= 0:
        raise ValueError("chunk-size 必须大于 0")

    windows_exe = find_single(input_dir, "*.exe", "Windows NSIS 安装包")
    mac_zip = find_single(input_dir, "*.zip", "macOS ZIP 更新包")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    manifest = {
        "schemaVersion": 1,
        "version": version,
        "releaseDate": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "platforms": {
            "windows-x64": split_artifact(windows_exe, output_dir, chunk_size),
            "macos-arm64": split_artifact(mac_zip, output_dir, chunk_size),
        },
    }
    manifest_path = output_dir / "gotbotnovel-update.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest = prepare(args.input, args.output, args.version, args.chunk_size)
    for platform, artifact in manifest["platforms"].items():
        print(
            f"{platform}: {artifact['filename']} -> {len(artifact['parts'])} parts, "
            f"{artifact['size']} bytes"
        )


if __name__ == "__main__":
    main()
