"""
用户密码管理模块 - 使用数据库存储
"""
import asyncio
import hashlib
import hmac
import secrets
from typing import Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings


class UserPasswordManager:
    """用户密码管理器 - 使用数据库存储（PostgreSQL共享库）"""
    
    def __init__(self):
        """初始化密码管理器"""
        pass
    
    async def _get_session(self) -> AsyncSession:
        """获取数据库会话 - 使用共享的PostgreSQL引擎"""
        from app.database import get_engine
        
        # 使用共享的PostgreSQL引擎（user_id使用特殊标识）
        engine = await get_engine("_global_users_")
        
        session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        return session_maker()
    
    def _hash_password(self, password: str) -> str:
        """密码哈希"""
        salt = secrets.token_hex(16)
        iterations = 260000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        return f"pbkdf2_sha256${iterations}${salt}${digest}"

    def _verify_hash(self, password: str, stored_hash: str) -> bool:
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                _, iterations, salt, digest = stored_hash.split("$", 3)
                candidate = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode(),
                    salt.encode(),
                    int(iterations),
                ).hex()
                return hmac.compare_digest(candidate, digest)
            except Exception:
                return False

        # Legacy unsalted SHA-256 hash support for existing deployments.
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(legacy_hash, stored_hash)
    
    @staticmethod
    def generate_random_password() -> str:
        """生成适合首次登录使用的高强度随机密码。"""
        return secrets.token_urlsafe(18)

    async def set_password(
        self,
        user_id: str,
        username: str,
        password: Optional[str] = None,
        *,
        has_custom_password: Optional[bool] = None,
    ) -> str:
        """设置用户密码；未提供密码时生成随机临时密码。"""
        from app.models.user import UserPassword as UserPasswordModel

        actual_password = password or self.generate_random_password()
        is_custom = password is not None if has_custom_password is None else has_custom_password
        
        async with await self._get_session() as session:
            # 查询密码记录是否存在
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if pwd_record:
                # 更新现有密码
                pwd_record.username = username
                pwd_record.password_hash = self._hash_password(actual_password)
                pwd_record.has_custom_password = is_custom
                pwd_record.updated_at = datetime.now()
            else:
                # 创建新密码记录
                pwd_record = UserPasswordModel(
                    user_id=user_id,
                    username=username,
                    password_hash=self._hash_password(actual_password),
                    has_custom_password=is_custom,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                session.add(pwd_record)
            
            await session.commit()
            
            return actual_password
    
    async def update_credentials(self, user_id: str, username: str, password: str) -> None:
        """原子更新用户登录账号和密码。"""
        from app.models.user import User as UserModel, UserPassword as UserPasswordModel

        normalized_username = username.strip()
        async with await self._get_session() as session:
            duplicate_user = await session.execute(
                select(UserModel).where(
                    UserModel.username == normalized_username,
                    UserModel.user_id != user_id,
                )
            )
            duplicate_password = await session.execute(
                select(UserPasswordModel).where(
                    UserPasswordModel.username == normalized_username,
                    UserPasswordModel.user_id != user_id,
                )
            )
            if duplicate_user.scalar_one_or_none() or duplicate_password.scalar_one_or_none():
                raise ValueError("账号已存在")

            user_result = await session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if not user:
                raise ValueError("用户不存在")

            password_result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            password_record = password_result.scalar_one_or_none()
            if not password_record:
                password_record = UserPasswordModel(
                    user_id=user_id,
                    username=normalized_username,
                    password_hash=self._hash_password(password),
                    has_custom_password=True,
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                session.add(password_record)
            else:
                password_record.username = normalized_username
                password_record.password_hash = self._hash_password(password)
                password_record.has_custom_password = True
                password_record.updated_at = datetime.now()

            user.username = normalized_username
            user.last_login = datetime.now()
            await session.commit()

    async def verify_password(self, user_id: str, password: str) -> bool:
        """
        验证用户密码
        
        Args:
            user_id: 用户ID
            password: 待验证的密码
            
        Returns:
            是否验证通过
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return False
            
            verified = self._verify_hash(password, pwd_record.password_hash)
            if verified and not pwd_record.password_hash.startswith("pbkdf2_sha256$"):
                pwd_record.password_hash = self._hash_password(password)
                pwd_record.updated_at = datetime.now()
                await session.commit()
            return verified
    
    async def has_password(self, user_id: str) -> bool:
        """
        检查用户是否已设置密码
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否已设置密码
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            return pwd_record is not None
    
    async def has_custom_password(self, user_id: str) -> bool:
        """
        检查用户是否设置了自定义密码（非默认密码）
        
        Args:
            user_id: 用户ID
            
        Returns:
            是否使用自定义密码
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return False
            
            return pwd_record.has_custom_password
    
    async def get_username(self, user_id: str) -> Optional[str]:
        """
        获取用户名
        
        Args:
            user_id: 用户ID
            
        Returns:
            用户名，如果不存在返回None
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return None
            
            return pwd_record.username


# 全局密码管理器实例
password_manager = UserPasswordManager()
