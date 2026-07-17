import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select

from app import bootstrap_admin
from app.bootstrap_admin import clear_initial_credentials, ensure_initial_local_admin
from app.config import settings
from app.database import close_db, get_engine
from app.models.user import User, UserPassword
from app.user_password import password_manager


class BootstrapAdminTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.original_database_url = settings.database_url
        self.original_local_auth_enabled = settings.LOCAL_AUTH_ENABLED
        self.original_credentials_file = bootstrap_admin.INITIAL_CREDENTIALS_FILE

        settings.database_url = f"sqlite+aiosqlite:///{Path(self.temp_dir.name) / 'test.db'}"
        settings.LOCAL_AUTH_ENABLED = True
        bootstrap_admin.INITIAL_CREDENTIALS_FILE = Path(self.temp_dir.name) / "initial_admin_credentials.json"

        engine = await get_engine("test")
        async with engine.begin() as connection:
            await connection.run_sync(User.__table__.create)
            await connection.run_sync(UserPassword.__table__.create)

    async def asyncTearDown(self):
        await close_db()
        settings.database_url = self.original_database_url
        settings.LOCAL_AUTH_ENABLED = self.original_local_auth_enabled
        bootstrap_admin.INITIAL_CREDENTIALS_FILE = self.original_credentials_file
        self.temp_dir.cleanup()

    async def test_first_start_creates_reusable_random_temporary_admin(self):
        first = await ensure_initial_local_admin()
        second = await ensure_initial_local_admin()

        self.assertIsNotNone(first)
        self.assertEqual(first, second)
        self.assertRegex(first["username"], r"^admin_[0-9a-f]{8}$")
        self.assertGreaterEqual(len(first["password"]), 20)
        self.assertTrue(await password_manager.verify_password(first["user_id"], first["password"]))
        self.assertFalse(await password_manager.has_custom_password(first["user_id"]))

        stored = json.loads(bootstrap_admin.INITIAL_CREDENTIALS_FILE.read_text(encoding="utf-8"))
        self.assertEqual(stored["username"], first["username"])

        engine = await get_engine("test")
        async with engine.connect() as connection:
            result = await connection.execute(select(User))
            self.assertEqual(len(result.scalars().all()), 1)

    async def test_credentials_update_marks_custom_and_removes_temporary_file(self):
        credentials = await ensure_initial_local_admin()

        await password_manager.update_credentials(
            credentials["user_id"],
            "my-admin",
            "my-secure-password",
        )
        clear_initial_credentials(credentials["user_id"])

        self.assertFalse(bootstrap_admin.INITIAL_CREDENTIALS_FILE.exists())
        self.assertTrue(await password_manager.has_custom_password(credentials["user_id"]))
        self.assertTrue(await password_manager.verify_password(credentials["user_id"], "my-secure-password"))
        self.assertFalse(await password_manager.verify_password(credentials["user_id"], credentials["password"]))
        self.assertIsNone(await ensure_initial_local_admin())


if __name__ == "__main__":
    unittest.main()
