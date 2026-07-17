import base64
import hashlib
import importlib.util
import json
from pathlib import Path

import yaml

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
                "parts": [{"name": "win.part000", "size": 5, "sha256": "x"}],
            },
            "macos-arm64": {
                "filename": "GotBotNovel-1.0.3-arm64-mac.zip",
                "size": 7,
                "sha512": "mac-sha512",
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
        rebuilt = b"".join((output_dir / part["name"]).read_bytes() for part in artifact["parts"])
        assert rebuilt == original.read_bytes()
        expected_sha512 = base64.b64encode(hashlib.sha512(rebuilt).digest()).decode("ascii")
        assert artifact["sha512"] == expected_sha512


def test_publish_removes_old_manifest_before_uploading_parts(tmp_path: Path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "artifact.part000").write_bytes(b"part-0")
    (assets / "artifact.part001").write_bytes(b"part-1")
    (assets / "gotbotnovel-update.json").write_text("{}", encoding="utf-8")
    events = []

    class FakePublisher:
        def __init__(self, *args, **kwargs):
            pass

        def get_or_create_release(self, **kwargs):
            return {"id": 7}

        def list_attachments(self, release_id):
            return [
                {"id": 10, "name": "gotbotnovel-update.json"},
                {"id": 11, "name": "artifact.part000"},
            ]

        def delete_attachment(self, release_id, attachment_id):
            events.append(("delete", attachment_id))

        def upload_attachment(self, release_id, path):
            events.append(("upload", path.name))
            return {"name": path.name}

        def close(self):
            events.append(("close", None))

    monkeypatch.setattr(_publish_module, "GiteePublisher", FakePublisher)
    _publish_module.publish(
        assets_dir=assets,
        token="token",
        owner="owner",
        repo="repo",
        tag="v1.0.3",
        target="main",
        api_base="https://gitee.com/api/v5",
    )

    assert events == [
        ("delete", 10),
        ("delete", 11),
        ("upload", "artifact.part000"),
        ("upload", "artifact.part001"),
        ("upload", "gotbotnovel-update.json"),
        ("close", None),
    ]


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
