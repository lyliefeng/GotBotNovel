#!/usr/bin/env python3
"""创建/更新 Gitee Release，并上传分片化桌面更新附件。"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote

import httpx

MANIFEST_NAME = "gotbotnovel-update.json"
PRIMARY_PLATFORM = "windows-x64"
MANAGED_PART_RE = re.compile(r"^GotBotNovel.*\.part\d{3}$")


class GiteePublisher:
    def __init__(self, token: str, owner: str, repo: str, api_base: str) -> None:
        self.token = token
        self.owner = owner
        self.repo = repo
        self.api_base = api_base.rstrip("/")
        self.client = httpx.Client(
            timeout=httpx.Timeout(300.0, connect=30.0), follow_redirects=True
        )

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
            response = self.request(
                "PATCH", self.api(f"releases/{release['id']}"), data=form
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("id"):
            raise RuntimeError("Gitee Release API 未返回有效的 Release 数据")
        return payload

    def list_releases(self) -> list[dict[str, Any]]:
        response = self.request(
            "GET",
            self.api("releases"),
            params={"access_token": self.token, "per_page": 100, "page": 1},
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Gitee Release 列表格式无效")
        return payload

    def list_attachments(self, release_id: int) -> list[dict[str, Any]]:
        response = self.request(
            "GET",
            self.api(f"releases/{release_id}/attach_files"),
            params={"access_token": self.token, "per_page": 100, "direction": "asc"},
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

    def cleanup_other_update_attachments(self, current_release_id: int) -> None:
        """清理旧版本更新附件，避免滚动发布超过单仓库 1 GB 配额。"""
        for release in self.list_releases():
            release_id = release.get("id") if isinstance(release, dict) else None
            if not isinstance(release_id, int) or release_id == current_release_id:
                continue
            for attachment in self.list_attachments(release_id):
                name = attachment.get("name") if isinstance(attachment, dict) else None
                attachment_id = attachment.get("id") if isinstance(attachment, dict) else None
                if not isinstance(name, str) or not isinstance(attachment_id, int):
                    continue
                if name == MANIFEST_NAME or MANAGED_PART_RE.fullmatch(name):
                    print(f"清理旧 Release 更新附件: {name}")
                    self.delete_attachment(release_id, attachment_id)

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
                    error = httpx.HTTPStatusError(
                        f"Gitee 附件上传返回 {response.status_code}: {detail}",
                        request=response.request,
                        response=response,
                    )
                    # 配额错误不会因重试恢复，立即交给上层处理。
                    if "仓库附件配额" in detail:
                        raise RuntimeError(str(error)) from error
                    raise error
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
    replace_existing: bool = False,
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

    if replace_existing:
        # 先一次性删除所有同名旧附件，再开始上传。这样中断后可不带本参数
        # 重试：已上传的新附件会按大小保留，其余附件仍保持缺失并继续上传。
        for name in desired:
            old = existing.pop(name, None)
            if old:
                print(f"删除同版本重发的已有附件: {name}")
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


def _artifact_part_paths(
    assets_dir: Path, platform_name: str, artifact: Any
) -> list[Path]:
    if not isinstance(artifact, dict) or not isinstance(artifact.get("parts"), list):
        raise ValueError(f"{platform_name} 更新清单无效")
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
    return part_paths


def publish(
    assets_dir: Path,
    token: str,
    owner: str,
    repo: str,
    macos_repo: str,
    tag: str,
    target: str,
    macos_target: str,
    api_base: str,
    replace_existing: bool = False,
) -> None:
    """在两个公开 Gitee 仓库中滚动发布桌面更新文件。

    Gitee 明确返回单仓库附件配额 1 GB。Windows 更新包约 748 MB，留在
    主代码仓库；macOS ZIP 约 876 MB，发布到独立公开仓库。正式 Release
    清单记录跨仓库位置，后端按清单重新拼接并校验文件。
    """
    source_manifest = _load_manifest(assets_dir)
    published_manifest = deepcopy(source_manifest)
    platforms = published_manifest["platforms"]
    if PRIMARY_PLATFORM not in platforms:
        raise ValueError(f"更新清单缺少主平台: {PRIMARY_PLATFORM}")

    main_publisher = GiteePublisher(token, owner, repo, api_base)
    macos_publisher = GiteePublisher(token, owner, macos_repo, api_base)
    try:
        # 先完成 macOS 仓库，确保正式清单出现时全部跨仓库分片已经可用。
        for platform_name, artifact in platforms.items():
            if platform_name == PRIMARY_PLATFORM:
                for field in ("releaseOwner", "releaseRepo", "releaseTag"):
                    artifact.pop(field, None)
                continue
            part_paths = _artifact_part_paths(assets_dir, platform_name, artifact)
            asset_tag = f"{tag}-{platform_name}"
            artifact["releaseOwner"] = owner
            artifact["releaseRepo"] = macos_repo
            artifact["releaseTag"] = asset_tag
            asset_release = macos_publisher.get_or_create_release(
                tag=asset_tag,
                target=macos_target,
                name=f"GotBotNovel {tag} {platform_name} 更新分片",
                body=(
                    f"GotBotNovel {tag} 的 {platform_name} 自动更新分片。"
                    f"正式更新清单位于 {owner}/{repo}。"
                ),
                prerelease=True,
            )
            asset_release_id = int(asset_release["id"])
            macos_publisher.cleanup_other_update_attachments(asset_release_id)
            print(f"同步 macOS 更新仓库 Release: {asset_tag}")
            _sync_attachments(
                macos_publisher,
                asset_release_id,
                part_paths,
                remove_obsolete=True,
                replace_existing=replace_existing,
            )

        release_body = (
            "GotBotNovel 桌面自动更新文件。Windows 分片和更新清单保存在本 "
            f"Release；macOS 更新分片保存在 {owner}/{macos_repo}。"
        )
        # 先保持 prerelease，只有全部 Windows 分片和清单就绪后才切为 latest。
        stable_release = main_publisher.get_or_create_release(
            tag=tag,
            target=target,
            name=f"GotBotNovel {tag}",
            body=release_body,
            prerelease=True,
        )
        stable_release_id = int(stable_release["id"])
        main_publisher.cleanup_other_update_attachments(stable_release_id)
        primary_paths = _artifact_part_paths(
            assets_dir, PRIMARY_PLATFORM, platforms[PRIMARY_PLATFORM]
        )

        with tempfile.TemporaryDirectory(prefix="gotbot-gitee-manifest-") as temp_dir:
            manifest_path = Path(temp_dir) / MANIFEST_NAME
            manifest_path.write_text(
                json.dumps(published_manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"同步正式 Release: {tag}")
            _sync_attachments(
                main_publisher,
                stable_release_id,
                [*primary_paths, manifest_path],
                remove_obsolete=True,
                replace_existing=replace_existing,
            )

        main_publisher.get_or_create_release(
            tag=tag,
            target=target,
            name=f"GotBotNovel {tag}",
            body=release_body,
            prerelease=False,
        )
        print(f"正式 Release 已切换为 latest: {tag}")
    finally:
        macos_publisher.close()
        main_publisher.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--macos-repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--target", default="main")
    parser.add_argument("--macos-target", default="master")
    parser.add_argument("--api-base", default="https://gitee.com/api/v5")
    parser.add_argument(
        "--replace-existing",
        action="store_true",
        help="同一 tag 重发时删除并重新上传同名附件，即使文件大小相同",
    )
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
        macos_repo=args.macos_repo,
        tag=args.tag,
        target=args.target,
        macos_target=args.macos_target,
        api_base=args.api_base,
        replace_existing=args.replace_existing,
    )


if __name__ == "__main__":
    main()
