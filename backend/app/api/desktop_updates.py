"""Electron 桌面端更新源。

Gitee 社区版对单个文件有较小配额，而桌面安装包包含离线模型，体积较大。
发布流程会把安装包切分为多个 Release 附件；本路由把这些分片重新流式拼接，
为 electron-updater 提供标准 generic provider 所需的 latest.yml 和完整文件流。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator
from urllib.parse import quote, urlparse

import httpx
import yaml
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse, StreamingResponse

from app.config import settings
from app.logger import get_logger

router = APIRouter(prefix="/desktop-updates", tags=["桌面自动更新"])
logger = get_logger(__name__)

MANIFEST_NAME = "gotbotnovel-update.json"
PLATFORM_BY_CHANNEL = {
    "latest.yml": "windows-x64",
    "latest-mac.yml": "macos-arm64",
}


@dataclass(frozen=True)
class ReleaseBundle:
    fetched_at: float
    release: dict[str, Any]
    manifest: dict[str, Any]
    attachments: dict[str, dict[str, Any]]


_cache: ReleaseBundle | None = None
_cache_lock = asyncio.Lock()


def _repository_api_url(owner: str, repo: str, path: str) -> str:
    base = settings.DESKTOP_UPDATE_GITEE_API_BASE.rstrip("/")
    return (
        f"{base}/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/"
        f"{path.lstrip('/')}"
    )


def _api_url(path: str) -> str:
    return _repository_api_url(
        settings.DESKTOP_UPDATE_GITEE_OWNER, settings.DESKTOP_UPDATE_GITEE_REPO, path
    )


def _validate_download_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError("Gitee 附件下载地址必须是 HTTPS")
    allowed_hosts = tuple(settings.DESKTOP_UPDATE_ALLOWED_DOWNLOAD_HOSTS)
    if not any(parsed.hostname == host or parsed.hostname.endswith(f".{host}") for host in allowed_hosts):
        raise ValueError(f"不允许的更新下载域名: {parsed.hostname}")


def _validate_manifest(manifest: Any) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ValueError("更新清单格式或 schemaVersion 无效")
    if not isinstance(manifest.get("version"), str) or not manifest["version"]:
        raise ValueError("更新清单缺少 version")
    platforms = manifest.get("platforms")
    if not isinstance(platforms, dict):
        raise ValueError("更新清单缺少 platforms")

    for platform_name, artifact in platforms.items():
        if not isinstance(artifact, dict):
            raise ValueError(f"{platform_name} 更新信息无效")
        filename = artifact.get("filename")
        parts = artifact.get("parts")
        if not isinstance(filename, str) or not filename:
            raise ValueError(f"{platform_name} 缺少 filename")
        if not isinstance(artifact.get("sha512"), str) or not artifact["sha512"]:
            raise ValueError(f"{platform_name} 缺少 sha512")
        if not isinstance(artifact.get("size"), int) or artifact["size"] <= 0:
            raise ValueError(f"{platform_name} size 无效")
        release_tag = artifact.get("releaseTag")
        if release_tag is not None and (not isinstance(release_tag, str) or not release_tag):
            raise ValueError(f"{platform_name} releaseTag 无效")
        for field in ("releaseOwner", "releaseRepo"):
            value = artifact.get(field)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"{platform_name} {field} 无效")
        if (artifact.get("releaseOwner") or artifact.get("releaseRepo")) and not release_tag:
            raise ValueError(f"{platform_name} 跨仓库更新缺少 releaseTag")
        if not isinstance(parts, list) or not parts:
            raise ValueError(f"{platform_name} 缺少分片")
        if sum(part.get("size", 0) for part in parts if isinstance(part, dict)) != artifact["size"]:
            raise ValueError(f"{platform_name} 分片大小与文件大小不一致")
        for part in parts:
            if (
                not isinstance(part, dict)
                or not isinstance(part.get("name"), str)
                or not isinstance(part.get("size"), int)
                or part["size"] <= 0
            ):
                raise ValueError(f"{platform_name} 包含无效分片")
    return manifest


async def _request_json(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


async def _release_attachments(
    client: httpx.AsyncClient,
    release: Any,
    *,
    label: str,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not isinstance(release, dict) or not isinstance(release.get("id"), int):
        raise ValueError(f"{label} 缺少有效 Release id")
    attachment_list = await _request_json(
        client,
        _repository_api_url(
            owner or settings.DESKTOP_UPDATE_GITEE_OWNER,
            repo or settings.DESKTOP_UPDATE_GITEE_REPO,
            f"releases/{release['id']}/attach_files?per_page=100&direction=asc",
        ),
    )
    if not isinstance(attachment_list, list):
        raise ValueError(f"{label} 附件列表格式无效")
    return {
        item["name"]: item
        for item in attachment_list
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }


async def _fetch_release_bundle() -> ReleaseBundle:
    timeout = httpx.Timeout(settings.DESKTOP_UPDATE_HTTP_TIMEOUT_SECONDS, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        release = await _request_json(client, _api_url("releases/latest"))
        attachments = await _release_attachments(client, release, label="Gitee 最新 Release")
        manifest_attachment = attachments.get(MANIFEST_NAME)
        if not manifest_attachment:
            raise FileNotFoundError(f"最新 Gitee Release 缺少 {MANIFEST_NAME}")
        manifest_url = manifest_attachment.get("browser_download_url")
        if not isinstance(manifest_url, str):
            raise ValueError("更新清单附件缺少 browser_download_url")
        _validate_download_url(manifest_url)
        manifest = _validate_manifest(await _request_json(client, manifest_url))

        # 大型安装包按平台保存在 prerelease 辅助 Release。旧清单没有
        # releaseTag 时仍回退到正式 Release，兼容早期发布格式。
        attachments_by_source: dict[
            tuple[str, str, str], dict[str, dict[str, Any]]
        ] = {}
        release_sources = {
            (
                artifact.get("releaseOwner") or settings.DESKTOP_UPDATE_GITEE_OWNER,
                artifact.get("releaseRepo") or settings.DESKTOP_UPDATE_GITEE_REPO,
                artifact["releaseTag"],
            )
            for artifact in manifest["platforms"].values()
            if artifact.get("releaseTag")
        }
        for release_owner, release_repo, release_tag in sorted(release_sources):
            tagged_release = await _request_json(
                client,
                _repository_api_url(
                    release_owner,
                    release_repo,
                    f"releases/tags/{quote(release_tag, safe='')}",
                ),
            )
            source = (release_owner, release_repo, release_tag)
            attachments_by_source[source] = await _release_attachments(
                client,
                tagged_release,
                label=(
                    f"Gitee 辅助 Release {release_owner}/{release_repo}@{release_tag}"
                ),
                owner=release_owner,
                repo=release_repo,
            )

        for platform_name, artifact in manifest["platforms"].items():
            release_tag = artifact.get("releaseTag")
            if release_tag:
                source = (
                    artifact.get("releaseOwner")
                    or settings.DESKTOP_UPDATE_GITEE_OWNER,
                    artifact.get("releaseRepo") or settings.DESKTOP_UPDATE_GITEE_REPO,
                    release_tag,
                )
                platform_attachments = attachments_by_source[source]
            else:
                platform_attachments = attachments
            for part in artifact["parts"]:
                attachment = platform_attachments.get(part["name"])
                if not attachment:
                    raise FileNotFoundError(
                        f"{platform_name} Release 缺少更新分片: {part['name']}"
                    )
                download_url = attachment.get("browser_download_url")
                if not isinstance(download_url, str):
                    raise ValueError(f"分片缺少下载地址: {part['name']}")
                _validate_download_url(download_url)
                attachments[part["name"]] = attachment

        return ReleaseBundle(
            fetched_at=time.monotonic(),
            release=release,
            manifest=manifest,
            attachments=attachments,
        )


async def get_release_bundle(*, force_refresh: bool = False) -> ReleaseBundle:
    global _cache
    ttl = settings.DESKTOP_UPDATE_CACHE_SECONDS
    if not force_refresh and _cache and time.monotonic() - _cache.fetched_at < ttl:
        return _cache

    async with _cache_lock:
        if not force_refresh and _cache and time.monotonic() - _cache.fetched_at < ttl:
            return _cache
        _cache = await _fetch_release_bundle()
        return _cache


def _artifact_for_filename(bundle: ReleaseBundle, filename: str) -> dict[str, Any]:
    for artifact in bundle.manifest["platforms"].values():
        if artifact["filename"] == filename:
            return artifact
    raise KeyError(filename)


def _update_yaml(bundle: ReleaseBundle, platform_name: str) -> str:
    artifact = bundle.manifest["platforms"].get(platform_name)
    if not artifact:
        raise KeyError(platform_name)
    file_url = f"files/{quote(artifact['filename'], safe='')}"
    data = {
        "version": bundle.manifest["version"],
        "files": [
            {
                "url": file_url,
                "sha512": artifact["sha512"],
                "size": artifact["size"],
            }
        ],
        "path": file_url,
        "sha512": artifact["sha512"],
        "releaseDate": bundle.manifest.get("releaseDate") or bundle.release.get("created_at"),
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def _parse_range(range_header: str | None, total_size: int) -> tuple[int, int, bool]:
    if not range_header:
        return 0, total_size - 1, False
    if not range_header.startswith("bytes=") or "," in range_header:
        raise ValueError("仅支持单个 bytes Range")
    value = range_header[6:].strip()
    start_text, separator, end_text = value.partition("-")
    if not separator:
        raise ValueError("Range 格式无效")
    if not start_text:
        suffix = int(end_text)
        if suffix <= 0:
            raise ValueError("Range 后缀无效")
        start = max(total_size - suffix, 0)
        end = total_size - 1
    else:
        start = int(start_text)
        end = int(end_text) if end_text else total_size - 1
    if start < 0 or start >= total_size or end < start:
        raise ValueError("Range 超出文件范围")
    return start, min(end, total_size - 1), True


async def _stream_upstream_slice(
    client: httpx.AsyncClient,
    url: str,
    start: int,
    end: int,
    part_size: int,
) -> AsyncIterator[bytes]:
    headers: dict[str, str] = {}
    if start != 0 or end != part_size - 1:
        headers["Range"] = f"bytes={start}-{end}"

    async with client.stream("GET", url, headers=headers) as response:
        response.raise_for_status()
        remaining = end - start + 1
        skip = 0 if response.status_code == 206 else start
        async for chunk in response.aiter_bytes(1024 * 1024):
            if skip:
                if len(chunk) <= skip:
                    skip -= len(chunk)
                    continue
                chunk = chunk[skip:]
                skip = 0
            if remaining <= 0:
                break
            if len(chunk) > remaining:
                chunk = chunk[:remaining]
            remaining -= len(chunk)
            if chunk:
                yield chunk
        if remaining:
            raise httpx.StreamError(f"Gitee 分片响应长度不足，还缺少 {remaining} bytes")


async def _stream_artifact(
    bundle: ReleaseBundle,
    artifact: dict[str, Any],
    start: int,
    end: int,
) -> AsyncIterator[bytes]:
    timeout = httpx.Timeout(settings.DESKTOP_UPDATE_HTTP_TIMEOUT_SECONDS, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        offset = 0
        for part in artifact["parts"]:
            part_start = offset
            part_end = offset + part["size"] - 1
            offset = part_end + 1
            if part_end < start or part_start > end:
                continue
            local_start = max(start, part_start) - part_start
            local_end = min(end, part_end) - part_start
            attachment = bundle.attachments[part["name"]]
            async for chunk in _stream_upstream_slice(
                client,
                attachment["browser_download_url"],
                local_start,
                local_end,
                part["size"],
            ):
                yield chunk


async def _bundle_or_http_error() -> ReleaseBundle:
    if not settings.DESKTOP_UPDATE_ENABLED:
        raise HTTPException(status_code=404, detail="桌面自动更新未启用")
    try:
        return await get_release_bundle()
    except httpx.HTTPStatusError as exc:
        logger.warning("访问 Gitee 更新源失败: %s", exc)
        raise HTTPException(status_code=502, detail="Gitee 更新源暂时不可用") from exc
    except (httpx.HTTPError, ValueError, FileNotFoundError) as exc:
        logger.warning("读取 Gitee 更新信息失败: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{channel_file}", response_class=PlainTextResponse)
async def update_channel(channel_file: str) -> PlainTextResponse:
    platform_name = PLATFORM_BY_CHANNEL.get(channel_file)
    if not platform_name:
        raise HTTPException(status_code=404, detail="未知更新通道")
    bundle = await _bundle_or_http_error()
    try:
        content = _update_yaml(bundle, platform_name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"当前 Release 没有 {platform_name} 更新") from exc
    return PlainTextResponse(
        content,
        media_type="application/yaml",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/files/{filename:path}")
async def download_update_file(filename: str, request: Request) -> StreamingResponse:
    bundle = await _bundle_or_http_error()
    try:
        artifact = _artifact_for_filename(bundle, filename)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="更新文件不存在") from exc

    total_size = artifact["size"]
    try:
        start, end, partial = _parse_range(request.headers.get("range"), total_size)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=416,
            detail=str(exc),
            headers={"Content-Range": f"bytes */{total_size}"},
        ) from exc

    headers = {
        "Accept-Ranges": "bytes",
        "Content-Length": str(end - start + 1),
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
        "Cache-Control": "no-store",
    }
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{total_size}"
    return StreamingResponse(
        _stream_artifact(bundle, artifact, start, end),
        status_code=206 if partial else 200,
        media_type="application/octet-stream",
        headers=headers,
    )
