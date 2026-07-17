"""首次启动本地管理员初始化。"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import DATA_DIR, settings
from app.database import get_engine
from app.logger import get_logger
from app.models.user import User as UserModel, UserPassword as UserPasswordModel
from app.user_password import password_manager

logger = get_logger(__name__)
INITIAL_CREDENTIALS_FILE = Path(DATA_DIR) / "initial_admin_credentials.json"


def _random_username() -> str:
    return f"admin_{secrets.token_hex(4)}"


def _load_credentials_file() -> dict | None:
    try:
        data = json.loads(INITIAL_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        if data.get("username") and data.get("password"):
            return data
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return None
    return None


def _write_credentials_file(credentials: dict) -> None:
    INITIAL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = INITIAL_CREDENTIALS_FILE.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(credentials, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(temporary_path, 0o600)
    os.replace(temporary_path, INITIAL_CREDENTIALS_FILE)
    os.chmod(INITIAL_CREDENTIALS_FILE, 0o600)


def clear_initial_credentials(user_id: str) -> None:
    """用户完成账号密码设置后删除临时凭据文件。"""
    credentials = _load_credentials_file()
    if credentials and credentials.get("user_id") == user_id:
        INITIAL_CREDENTIALS_FILE.unlink(missing_ok=True)


async def _get_session() -> AsyncSession:
    engine = await get_engine("_global_users_")
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()


async def ensure_initial_local_admin() -> dict | None:
    """确保系统至少有一个可使用本地密码登录的管理员。"""
    if not settings.LOCAL_AUTH_ENABLED:
        return None

    async with await _get_session() as session:
        admin_result = await session.execute(
            select(UserModel).where(UserModel.is_admin.is_(True)).order_by(UserModel.created_at.asc())
        )
        admins = list(admin_result.scalars().all())

        for admin in admins:
            password_result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == admin.user_id)
            )
            password_record = password_result.scalar_one_or_none()
            if password_record and password_record.has_custom_password:
                INITIAL_CREDENTIALS_FILE.unlink(missing_ok=True)
                return None

        target_admin = admins[0] if admins else None
        saved_credentials = _load_credentials_file()

        if target_admin and saved_credentials and saved_credentials.get("user_id") == target_admin.user_id:
            logger.warning(
                "首次登录临时管理员尚未完成账号密码设置，凭据文件：%s",
                INITIAL_CREDENTIALS_FILE,
            )
            return saved_credentials

        username = _random_username()
        while True:
            duplicate = await session.execute(select(UserModel).where(UserModel.username == username))
            if duplicate.scalar_one_or_none() is None:
                break
            username = _random_username()

        password = password_manager.generate_random_password()
        if target_admin is None:
            user_id = f"local_{secrets.token_hex(12)}"
            target_admin = UserModel(
                user_id=user_id,
                username=username,
                display_name=settings.LOCAL_AUTH_DISPLAY_NAME,
                avatar_url=None,
                trust_level=9,
                is_admin=True,
                linuxdo_id=user_id,
                created_at=datetime.now(timezone.utc),
                last_login=datetime.now(timezone.utc),
            )
            session.add(target_admin)
        else:
            target_admin.username = username
            target_admin.is_admin = True

        await session.commit()
        await session.refresh(target_admin)

    await password_manager.set_password(
        target_admin.user_id,
        username,
        password,
        has_custom_password=False,
    )

    credentials = {
        "user_id": target_admin.user_id,
        "username": username,
        "password": password,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "instruction": "首次登录后必须设置自己的账号和密码；设置完成后本文件会自动删除。",
    }
    _write_credentials_file(credentials)

    logger.warning(
        "\n%s\n首次登录临时管理员已生成\n账号：%s\n密码：%s\n凭据文件：%s\n登录后必须立即设置自己的账号和密码。\n%s",
        "=" * 64,
        username,
        password,
        INITIAL_CREDENTIALS_FILE,
        "=" * 64,
    )
    return credentials
