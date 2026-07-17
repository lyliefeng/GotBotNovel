#!/usr/bin/env python3
"""创建/更新 Gitee Release，并上传分片化桌面更新附件。"""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path
from typing import Any
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
    ) -> dict[str, Any]:
        response = self.request("GET", self.api(f"releases/tags/{quote(tag, safe='')}"))
        form = {
            "access_token": self.token,
            "tag_name": tag,
            "name": name,
            "body": body,
            "target_commitish": target,
            "prerelease": "false",
        }
        if response.status_code == 404:
            response = self.request("POST", self.api("releases"), data=form)
        else:
            response.raise_for_status()
            release_id = response.json()["id"]
            response = self.request("PATCH", self.api(f"releases/{release_id}"), data=form)
        response.raise_for_status()
        return response.json()

    def list_attachments(self, release_id: int) -> list[dict[str, Any]]:
        response = self.request(
            "GET",
            self.api(f"releases/{release_id}/attach_files"),
            params={"per_page": 100, "direction": "asc"},
        )
        response.raise_for_status()
        return response.json()

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
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, OSError) as exc:
                if attempt == 5:
                    raise
                wait_seconds = min(5 * attempt, 20)
                print(f"Gitee 附件上传失败，第 {attempt}/5 次，{wait_seconds}s 后重试: {exc}")
                time.sleep(wait_seconds)
        raise RuntimeError(f"Gitee 附件上传失败: {path.name}")


def publish(
    assets_dir: Path,
    token: str,
    owner: str,
    repo: str,
    tag: str,
    target: str,
    api_base: str,
) -> None:
    paths = sorted(path for path in assets_dir.iterdir() if path.is_file())
    manifest = assets_dir / MANIFEST_NAME
    if manifest not in paths:
        raise FileNotFoundError(f"缺少 {manifest}")
    # 清单最后上传，避免客户端在分片尚未齐全时看到可用版本。
    paths = [path for path in paths if path != manifest] + [manifest]

    publisher = GiteePublisher(token, owner, repo, api_base)
    try:
        release = publisher.get_or_create_release(
            tag=tag,
            target=target,
            name=f"GotBotNovel {tag}",
            body="GotBotNovel 桌面自动更新文件。安装包按分片保存，由应用自动下载并校验。",
        )
        release_id = int(release["id"])
        existing = {item["name"]: item for item in publisher.list_attachments(release_id)}

        # 先移除旧清单。这样即使中途上传失败，客户端也不会读取到引用不完整分片的版本。
        old_manifest = existing.pop(MANIFEST_NAME, None)
        if old_manifest:
            print(f"删除已有附件: {MANIFEST_NAME}")
            publisher.delete_attachment(release_id, int(old_manifest["id"]))

        for path in paths:
            old = existing.get(path.name)
            if old:
                print(f"删除已有附件: {path.name}")
                publisher.delete_attachment(release_id, int(old["id"]))
            print(f"上传附件: {path.name} ({path.stat().st_size} bytes)")
            uploaded = publisher.upload_attachment(release_id, path)
            print(f"上传完成: {uploaded.get('name', path.name)}")
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
