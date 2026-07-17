import asyncio
import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml

import app.api.desktop_updates as desktop_updates
from app.api.desktop_updates import (
    ReleaseBundle,
    _api_url,
    _parse_range,
    _update_yaml,
    _validate_manifest,
)

_PREPARE_SPEC = importlib.util.spec_from_file_location(
    "prepare_gitee_update",
    Path(__file__).parents[1] / "packaging" / "prepare_gitee_update.py",
)
_prepare_module = importlib.util.module_from_spec(_PREPARE_SPEC)
assert _PREPARE_SPEC.loader is not None
_PREPARE_SPEC.loader.exec_module(_prepare_module)
prepare = _prepare_module.prepare

_PUBLISH_SPEC = importlib.util.spec_from_file_location(
    "publish_gitee_release",
    Path(__file__).parents[1] / "packaging" / "publish_gitee_release.py",
)
_publish_module = importlib.util.module_from_spec(_PUBLISH_SPEC)
assert _PUBLISH_SPEC.loader is not None
_PUBLISH_SPEC.loader.exec_module(_publish_module)


def sample_manifest() -> dict:
    return {
        "schemaVersion": 1,
        "version": "1.0.3",
        "releaseDate": "2026-07-17T08:00:00Z",
        "platforms": {
            "windows-x64": {
                "filename": "GotBotNovel Setup 1.0.3.exe",
                "size": 5,
                "sha512": "windows-sha512",
                "releaseTag": "v1.0.3-windows-x64",
                "parts": [{"name": "win.part000", "size": 5, "sha256": "x"}],
            },
            "macos-arm64": {
                "filename": "GotBotNovel-1.0.3-arm64-mac.zip",
                "size": 7,
                "sha512": "mac-sha512",
                "releaseOwner": "lv-liefeng",
                "releaseRepo": "GotBotNovel-Updates-macOS",
                "releaseTag": "v1.0.3-macos-arm64",
                "parts": [{"name": "mac.part000", "size": 7, "sha256": "y"}],
            },
        },
    }


def test_default_gitee_release_url_uses_public_repository():
    assert (
        _api_url("releases/latest")
        == "https://gitee.com/api/v5/repos/lv-liefeng/GotBotNovel/releases/latest"
    )


def test_validate_manifest_and_render_windows_channel():
    manifest = _validate_manifest(sample_manifest())
    bundle = ReleaseBundle(
        fetched_at=0,
        release={"created_at": "2026-07-17T08:00:00Z"},
        manifest=manifest,
        attachments={},
    )
    result = yaml.safe_load(_update_yaml(bundle, "windows-x64"))
    assert result["version"] == "1.0.3"
    assert result["files"][0]["url"] == "files/GotBotNovel%20Setup%201.0.3.exe"
    assert result["files"][0]["size"] == 5
    assert result["sha512"] == "windows-sha512"


def test_validate_manifest_rejects_missing_part_bytes():
    manifest = sample_manifest()
    manifest["platforms"]["windows-x64"]["size"] = 6
    try:
        _validate_manifest(manifest)
    except ValueError as exc:
        assert "分片大小" in str(exc)
    else:
        raise AssertionError("无效清单未被拒绝")


def test_validate_manifest_rejects_empty_release_tag():
    manifest = sample_manifest()
    manifest["platforms"]["windows-x64"]["releaseTag"] = ""
    try:
        _validate_manifest(manifest)
    except ValueError as exc:
        assert "releaseTag" in str(exc)
    else:
        raise AssertionError("空 releaseTag 未被拒绝")


def test_fetch_release_bundle_reads_platform_parts_from_auxiliary_releases(monkeypatch):
    manifest = sample_manifest()
    manifest_url = "https://gitee.com/lv-liefeng/GotBotNovel/releases/download/v1.0.3/gotbotnovel-update.json"

    class DummyAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    async def fake_request_json(client, url):
        if url.endswith("/releases/latest"):
            return {"id": 1, "tag_name": "v1.0.3"}
        if "/releases/1/attach_files" in url:
            return [
                {
                    "name": "gotbotnovel-update.json",
                    "browser_download_url": manifest_url,
                }
            ]
        if url == manifest_url:
            return manifest
        if url.endswith("/releases/tags/v1.0.3-windows-x64"):
            return {"id": 2}
        if url.endswith("/releases/tags/v1.0.3-macos-arm64"):
            return {"id": 3}
        if "/releases/2/attach_files" in url:
            return [
                {
                    "name": "win.part000",
                    "browser_download_url": "https://gitee.com/download/win.part000",
                }
            ]
        if "/releases/3/attach_files" in url:
            return [
                {
                    "name": "mac.part000",
                    "browser_download_url": "https://gitee.com/download/mac.part000",
                }
            ]
        raise AssertionError(f"unexpected URL: {url}")

    monkeypatch.setattr(desktop_updates.httpx, "AsyncClient", DummyAsyncClient)
    monkeypatch.setattr(desktop_updates, "_request_json", fake_request_json)

    bundle = asyncio.run(desktop_updates._fetch_release_bundle())

    assert bundle.manifest == manifest
    assert bundle.attachments["win.part000"]["browser_download_url"].endswith(
        "win.part000"
    )
    assert bundle.attachments["mac.part000"]["browser_download_url"].endswith(
        "mac.part000"
    )


def test_parse_http_ranges():
    assert _parse_range(None, 100) == (0, 99, False)
    assert _parse_range("bytes=10-19", 100) == (10, 19, True)
    assert _parse_range("bytes=90-", 100) == (90, 99, True)
    assert _parse_range("bytes=-10", 100) == (90, 99, True)


def test_prepare_gitee_update_splits_and_hashes(tmp_path: Path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    exe = input_dir / "GotBotNovel Setup 1.0.3.exe"
    mac_zip = input_dir / "GotBotNovel-1.0.3-arm64-mac.zip"
    exe.write_bytes(b"windows-update")
    mac_zip.write_bytes(b"macos-update-file")

    manifest = prepare(input_dir, output_dir, "1.0.3", chunk_size=5)
    assert manifest["version"] == "1.0.3"
    assert len(manifest["platforms"]["windows-x64"]["parts"]) == 3
    assert len(manifest["platforms"]["macos-arm64"]["parts"]) == 4

    persisted = json.loads((output_dir / "gotbotnovel-update.json").read_text())
    for platform, original in (("windows-x64", exe), ("macos-arm64", mac_zip)):
        artifact = persisted["platforms"][platform]
        rebuilt = b"".join(
            (output_dir / part["name"]).read_bytes() for part in artifact["parts"]
        )
        assert rebuilt == original.read_bytes()
        expected_sha512 = base64.b64encode(hashlib.sha512(rebuilt).digest()).decode("ascii")
        assert artifact["sha512"] == expected_sha512


def test_publish_keeps_windows_in_main_repo_and_moves_macos_to_asset_repo(
    tmp_path: Path, monkeypatch
):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "win.part000").write_bytes(b"win00")
    (assets / "mac.part000").write_bytes(b"macos00")
    source_manifest = sample_manifest()
    (assets / "gotbotnovel-update.json").write_text(
        json.dumps(source_manifest), encoding="utf-8"
    )
    events = []
    uploaded_manifest = {}

    class FakePublisher:
        def __init__(self, token, owner, repo, api_base):
            self.repo = repo

        def get_or_create_release(self, **kwargs):
            events.append(
                ("release", self.repo, kwargs["tag"], kwargs["prerelease"])
            )
            if self.repo == "GotBotNovel-Updates-macOS":
                return {"id": 102}
            return {"id": 100}

        def cleanup_other_update_attachments(self, release_id):
            events.append(("cleanup", self.repo, release_id))

        def list_attachments(self, release_id):
            if self.repo == "GotBotNovel-Updates-macOS":
                return []
            return [
                {"id": 11, "name": "win.part000", "size": 5},
                {"id": 90, "name": "gotbotnovel-update.json", "size": 1},
                {"id": 91, "name": "obsolete.part000", "size": 9},
            ]

        def delete_attachment(self, release_id, attachment_id):
            events.append(("delete", self.repo, release_id, attachment_id))

        def upload_attachment(self, release_id, path):
            events.append(("upload", self.repo, release_id, path.name))
            if path.name == "gotbotnovel-update.json":
                uploaded_manifest.update(json.loads(path.read_text(encoding="utf-8")))
            return {"name": path.name}

        def close(self):
            events.append(("close", self.repo))

    monkeypatch.setattr(_publish_module, "GiteePublisher", FakePublisher)
    _publish_module.publish(
        assets_dir=assets,
        token="token",
        owner="lv-liefeng",
        repo="GotBotNovel",
        macos_repo="GotBotNovel-Updates-macOS",
        tag="v1.0.3",
        target="main",
        macos_target="master",
        api_base="https://gitee.com/api/v5",
    )

    assert events == [
        (
            "release",
            "GotBotNovel-Updates-macOS",
            "v1.0.3-macos-arm64",
            True,
        ),
        ("cleanup", "GotBotNovel-Updates-macOS", 102),
        ("upload", "GotBotNovel-Updates-macOS", 102, "mac.part000"),
        ("release", "GotBotNovel", "v1.0.3", True),
        ("cleanup", "GotBotNovel", 100),
        ("delete", "GotBotNovel", 100, 91),
        ("delete", "GotBotNovel", 100, 90),
        ("upload", "GotBotNovel", 100, "gotbotnovel-update.json"),
        ("release", "GotBotNovel", "v1.0.3", False),
        ("close", "GotBotNovel-Updates-macOS"),
        ("close", "GotBotNovel"),
    ]
    assert "releaseTag" not in uploaded_manifest["platforms"]["windows-x64"]
    assert uploaded_manifest["platforms"]["macos-arm64"]["releaseOwner"] == (
        "lv-liefeng"
    )
    assert uploaded_manifest["platforms"]["macos-arm64"]["releaseRepo"] == (
        "GotBotNovel-Updates-macOS"
    )
    assert uploaded_manifest["platforms"]["macos-arm64"]["releaseTag"] == (
        "v1.0.3-macos-arm64"
    )
    assert json.loads((assets / "gotbotnovel-update.json").read_text()) == source_manifest



def test_cleanup_other_update_attachments_removes_only_managed_assets():
    publisher = _publish_module.GiteePublisher(
        "token", "owner", "repo", "https://gitee.com/api/v5"
    )
    publisher.client.close()
    deleted = []
    publisher.list_releases = lambda: [{"id": 1}, {"id": 2}]
    publisher.list_attachments = lambda release_id: [
        {"id": 10, "name": "gotbotnovel-update.json"},
        {"id": 11, "name": "GotBotNovel Setup 1.0.2.exe.part000"},
        {"id": 12, "name": "manual-notes.txt"},
    ]
    publisher.delete_attachment = lambda release_id, attachment_id: deleted.append(
        (release_id, attachment_id)
    )

    publisher.cleanup_other_update_attachments(current_release_id=2)

    assert deleted == [(1, 10), (1, 11)]

def test_upload_retry_reopens_attachment_file(tmp_path: Path, monkeypatch):
    attachment = tmp_path / "chunk.part000"
    attachment.write_bytes(b"complete-payload")
    attempts = []

    class FakeResponse:
        status_code = 201

        def raise_for_status(self):
            return None

        def json(self):
            return {"name": attachment.name}

    class FakeClient:
        def post(self, url, data, files):
            attempts.append(files["file"][1].read())
            if len(attempts) == 1:
                raise _publish_module.httpx.ReadError("temporary failure")
            return FakeResponse()

        def close(self):
            pass

    monkeypatch.setattr(_publish_module.time, "sleep", lambda _: None)
    publisher = _publish_module.GiteePublisher(
        "token", "owner", "repo", "https://gitee.com/api/v5"
    )
    publisher.client.close()
    publisher.client = FakeClient()

    result = publisher.upload_attachment(7, attachment)

    assert result == {"name": attachment.name}
    assert attempts == [b"complete-payload", b"complete-payload"]


def test_get_or_create_release_treats_http_200_null_as_missing():
    calls = []

    class FakeResponse:
        def __init__(self, status_code, payload):
            self.status_code = status_code
            self._payload = payload

        def raise_for_status(self):
            if self.status_code >= 400:
                raise AssertionError(f"unexpected status {self.status_code}")

        def json(self):
            return self._payload

    publisher = _publish_module.GiteePublisher(
        "token", "owner", "repo", "https://gitee.com/api/v5"
    )
    publisher.client.close()

    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "GET":
            return FakeResponse(200, None)
        if method == "POST":
            return FakeResponse(201, {"id": 9, "tag_name": "v1.0.2"})
        raise AssertionError(f"unexpected method {method}")

    publisher.request = fake_request
    try:
        release = publisher.get_or_create_release(
            tag="v1.0.2",
            target="main",
            name="GotBotNovel v1.0.2",
            body="desktop updates",
        )
    finally:
        publisher.close()

    assert release == {"id": 9, "tag_name": "v1.0.2"}
    assert [call[0] for call in calls] == ["GET", "POST"]
    assert calls[1][2]["data"]["prerelease"] == "false"


def test_sync_attachments_replace_existing_reuploads_same_size(tmp_path: Path):
    attachment = tmp_path / "chunk.part000"
    attachment.write_bytes(b"new-content")
    events = []

    class FakePublisher:
        def list_attachments(self, release_id):
            return [
                {
                    "id": 42,
                    "name": attachment.name,
                    "size": attachment.stat().st_size,
                }
            ]

        def delete_attachment(self, release_id, attachment_id):
            events.append(("delete", release_id, attachment_id))

        def upload_attachment(self, release_id, path):
            events.append(("upload", release_id, path.name))
            return {"name": path.name}

    _publish_module._sync_attachments(
        FakePublisher(),
        7,
        [attachment],
        remove_obsolete=True,
        replace_existing=True,
    )

    assert events == [
        ("delete", 7, 42),
        ("upload", 7, attachment.name),
    ]
