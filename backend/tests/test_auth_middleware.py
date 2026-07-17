import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import Request
from fastapi.responses import JSONResponse

from app.middleware.auth_middleware import AuthMiddleware
from app.user_manager import User, user_manager
from app.user_password import password_manager


class AuthMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, path: str) -> Request:
        return Request(
            {
                "type": "http",
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "headers": [(b"cookie", b"session_token=test-token")],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
        )

    def _user(self) -> User:
        return User(
            user_id="user-1",
            username="temporary-user",
            display_name="Temporary User",
            trust_level=9,
            is_admin=True,
            linuxdo_id="user-1",
            created_at="2026-07-17T00:00:00+00:00",
            last_login="2026-07-17T00:00:00+00:00",
        )

    async def _dispatch(self, path: str, has_custom_password: bool):
        middleware = AuthMiddleware(lambda scope, receive, send: None)
        downstream = AsyncMock(return_value=JSONResponse({"ok": True}))

        with (
            patch("app.middleware.auth_middleware.verify_session_token", return_value="user-1"),
            patch.object(user_manager, "get_user", AsyncMock(return_value=self._user())),
            patch.object(
                password_manager,
                "has_custom_password",
                AsyncMock(return_value=has_custom_password),
            ),
        ):
            response = await middleware.dispatch(self._request(path), downstream)

        return response, downstream

    async def test_temporary_user_is_blocked_from_application_api(self):
        response, downstream = await self._dispatch("/api/projects", False)

        self.assertEqual(response.status_code, 428)
        self.assertEqual(json.loads(response.body), {"detail": "首次登录必须先设置自己的账号和密码"})
        downstream.assert_not_awaited()

    async def test_temporary_user_can_update_credentials(self):
        response, downstream = await self._dispatch("/api/auth/credentials", False)

        self.assertEqual(response.status_code, 200)
        downstream.assert_awaited_once()

    async def test_custom_user_can_access_application_api(self):
        response, downstream = await self._dispatch("/api/projects", True)

        self.assertEqual(response.status_code, 200)
        downstream.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
