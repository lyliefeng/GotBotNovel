#!/usr/bin/env python3
"""创建/更新 Gitee Release，并上传分片化桌面更新附件。"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import httpx

MANIFEST_NAME = "gotbotnovel-update.json"


class GiteePublisher:
    def __init__(self, token: str, owner: str, repo: str, api_base: str) -> None:
        self.token = token
        self.owner = owner
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self.client = httpx.Client(timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True)

    def close(self) -> None:
        self.client.close()

    def api(self, path: str) -> str:
        owner = quote(self.owner, safe="")
        repo = quote(self.repo, safe="")
        return f"{self.api_base}/repos/{owner}/{repo}/{path.lstrip('/')}"

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        last_error: Exception | None = None
        for attempt in range(1, 6):
            try:
                response = self.client.request(method, url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                return response
            except (httpx.HTTPError, OSError) as exc:
                last_error = exc
                if attempt == 5:
                    raise
                wait_seconds = min(5 * attempt, 20)
                print(f"Gitee 请求失败，第 {attempt}/5 次，{wait_seconds}s 后重试: {exc}")
                time.sleep(wait_seconds)
        raise RuntimeError(str(last_error))

    def get_or_create_release(
        self,
        tag: str,
        target: str,
        name: str,
        body: str,
        *,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        response = self.request("GET", self.api(f"releases/tags/{quote(tag, safe='')}"))
        form = {
            "access_token": self.token,
            "tag_name": tag,
            "name": name,
            "body": body,
            "target_commitish": target,
            "prerelease": "true" if prerelease else "false",
        }
        release = None
        if response.status_code != 404:
            response.raise_for_status()
            release = response.json()

        # Gitee 对不存在的 tag release 可能返回 HTTP 200 和 JSON null，
        # 而不是文档中常见的 404。两种情况都应创建 Release。
        if not isinstance(release, dict) or not release.get("id"):
            response = self.request("POST", self.api("releases"), data=form)
        else:
            release_id = release["id"]
            response = self.request("PATCH", self.api(f"releases/{release_id}"), data=form)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("Gitee Release API 未返回有效的 Release 数据")
        return payload

    def list_attachments(self, release_id: int) -> list[dict[str, Any]]:
        response = self.request(
            "GET",
            self.api(f"releases/{release_id}/attach_files"),
            params={"per_page": 100, "direction": "asc"},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Gitee Release 附件列表格式无效")
        return payload

    def delete_attachment(self, release_id: int, attachment_id: int) -> None:
        response = self.request(
            "DELETE",
            self.api(f"releases/{release_id}/attach_files/{attachment_id}"),
            params={"access_token": self.token},
        )
        response.raise_for_status()

    def upload_attachment(self, release_id: int, path: Path) -> dict[str, Any]:
        # 每次重试都重新打开文件，避免首次请求后文件游标停在 EOF，导致重试上传空附件。
        for attempt in range(1, 6):
            try:
                with path.open("rb") as handle:
                    response = self.client.post(
                        self.api(f"releases/{release_id}/attach_files"),
                        data={"access_token": self.token},
                        files={"file": (path.name, handle, "application/octet-stream")},
                    )
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                if response.status_code >= 400:
                    detail = response.text.strip().replace("\n", " ")[:500]
                    raise httpx.HTTPStatusError(
                        f"Gitee 附件上传返回 {response.status_code}: {detail}",
                        request=response.request,
                        response=response,
                    )
                payload = response.json()
                if not isinstance(payload, dict):
                    raise RuntimeError("Gitee 附件上传响应格式无效")
                return payload
            except (httpx.HTTPError, OSError) as exc:
                if attempt == 5:
                    raise
                wait_seconds = min(5 * attempt, 20)
                print(f"Gitee 附件上传失败，第 {attempt}/5 次，{wait_seconds}s 后重试: {exc}")
                time.sleep(wait_seconds)
        raise RuntimeError(f"Gitee 附件上传失败: {path.name}")


def _sync_attachments(
    publisher: GiteePublisher,
    release_id: int,
    paths: Iterable[Path],
    *,
    remove_obsolete: bool,
) -> None:
    desired = {path.name: path for path in paths}
    existing = {
        item["name"]: item
        for item in publisher.list_attachments(release_id)
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }

    if remove_obsolete:
        for name, old in existing.items():
            if name not in desired:
                print(f"删除不再需要的附件: {name}")
                publisher.delete_attachment(release_id, int(old["id"]))

    for name, path in desired.items():
        old = existing.get(name)
        expected_size = path.stat().st_size
        if old and int(old.get("size", -1)) == expected_size:
            print(f"保留已有附件: {name} ({expected_size} bytes)")
            continue
        if old:
            print(f"删除大小不匹配的已有附件: {name}")
            publisher.delete_attachment(release_id, int(old["id"]))
        print(f"上传附件: {name} ({expected_size} bytes)")
        uploaded = publisher.upload_attachment(release_id, path)
        print(f"上传完成: {uploaded.get('name', name)}")


def _load_manifest(assets_dir: Path) -> dict[str, Any]:
    manifest_path = assets_dir / MANIFEST_NAME
    if not manifest_path.is_file():
        raise FileNotFoundError(f"缺少 {manifest_path}")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("platforms"), dict):
        raise ValueError("更新清单缺少 platforms")
    return payload


def publish(
    assets_dir: Path,
    token: str,
    owner: str,
    repo: str,
    tag: str,
    target: str,
    api_base: str,
) -> None:
    """按平台发布分片，主 Release 只保存清单。

    实测 Gitee 单个 Release 接近 1 GiB 后继续上传大附件会返回 HTTP 400。
    Windows 和 macOS 更新包分别小于 1 GiB，因此放入两个 prerelease 辅助
    Release；正式 Release 保持 latest，只保存带 releaseTag 的更新清单。
    """
    source_manifest = _load_manifest(assets_dir)
    published_manifest = deepcopy(source_manifest)
    publisher = GiteePublisher(token, owner, repo, api_base)

    try:
        for platform_name, artifact in published_manifest["platforms"].items():
            if not isinstance(artifact, dict) or not isinstance(artifact.get("parts"), list):
                raise ValueError(f"{platform_name} 更新清单无效")
            asset_tag = f"{tag}-{platform_name}"
            artifact["releaseTag"] = asset_tag
            part_paths: list[Path] = []
            for part in artifact["parts"]:
                if not isinstance(part, dict) or not isinstance(part.get("name"), str):
                    raise ValueError(f"{platform_name} 包含无效分片")
                path = assets_dir / part["name"]
                if not path.is_file():
                    raise FileNotFoundError(f"缺少更新分片: {path}")
                if path.stat().st_size != part.get("size"):
                    raise ValueError(f"更新分片大小不匹配: {path.name}")
                part_paths.append(path)

            asset_release = publisher.get_or_create_release(
                tag=asset_tag,
                target=target,
                name=f"GotBotNovel {tag} {platform_name} 更新分片",
                body=(
                    f"GotBotNovel {tag} 的 {platform_name} 自动更新分片。"
                    "此辅助 Release 由正式 Release 的更新清单引用。"
                ),
                prerelease=True,
            )
            print(f"同步辅助 Release: {asset_tag}")
            _sync_attachments(
                publisher,
                int(asset_release["id"]),
                part_paths,
                remove_obsolete=True,
            )

        stable_release = publisher.get_or_create_release(
            tag=tag,
            target=target,
            name=f"GotBotNovel {tag}",
            body=(
                "GotBotNovel 桌面自动更新清单。大型安装包按平台拆分到 prerelease "
                "辅助 Release，由应用自动下载、拼接并校验。"
            ),
            prerelease=False,
        )
        stable_release_id = int(stable_release["id"])

        with tempfile.TemporaryDirectory(prefix="gotbot-gitee-manifest-") as temp_dir:
            manifest_path = Path(temp_dir) / MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(published_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"同步正式 Release 清单: {tag}")
            _sync_attachments(
                publisher,
                stable_release_id,
                [manifest_path],
                remove_obsolete=True,
            )
    finally:
        publisher.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", default="main")
    parser.add_argument("--api-base", default="https://gitee.com/api/v5")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    token = os.environ.get("GITEE_ACCESS_TOKEN", "").strip()
    if not token:
        raise SystemExit("缺少 GITEE_ACCESS_TOKEN")
    publish(
        assets_dir=args.assets,
        token=token,
        owner=args.owner,
        repo=args.repo,
        tag=args.tag,
        target=args.target,
        api_base=args.api_base,
    )


if __name__ == "__main__":
    main()
