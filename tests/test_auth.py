"""鉴权层离线测试（零外呼）。"""
import os
import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.auth import check_password, issue_token, verify_token  # noqa: E402


class TestToken(unittest.TestCase):
    def setUp(self):
        self._p = os.environ.get("JEVETO_PASSWORD")
        os.environ["JEVETO_PASSWORD"] = "pw-test"

    def tearDown(self):
        if self._p is None:
            os.environ.pop("JEVETO_PASSWORD", None)
        else:
            os.environ["JEVETO_PASSWORD"] = self._p

    def test_issue_and_verify(self):
        t = issue_token()["token"]
        self.assertTrue(verify_token(t))

    def test_tamper_and_garbage(self):
        for bad in ("", "fake", "a.b", issue_token()["token"][:-3] + "xxx"):
            self.assertFalse(verify_token(bad), bad)

    def test_expiry(self):
        t = issue_token(ttl=-1)["token"]          # 立刻过期
        self.assertFalse(verify_token(t))

    def test_token_does_not_survive_password_change(self):
        t = issue_token()["token"]
        self.assertTrue(verify_token(t))
        os.environ["JEVETO_PASSWORD"] = "another-pw"   # 换密码 → 旧 token 失效
        self.assertFalse(verify_token(t))

    def test_check_password(self):
        self.assertTrue(check_password("pw-test"))
        self.assertFalse(check_password("nope"))
        self.assertFalse(check_password(""))


class TestEndpoints(unittest.TestCase):
    """真起 app 测路由（TestClient，不出网）。"""

    def _client(self):
        from fastapi.testclient import TestClient

        from main import app
        return TestClient(app)

    def test_auth_disabled_without_password(self):
        saved = os.environ.pop("JEVETO_PASSWORD", None)
        try:
            c = self._client()
            self.assertEqual(c.get("/auth/status").json()["auth_required"], False)
            self.assertEqual(c.get("/agents").status_code, 200)    # 开发模式直通
        finally:
            if saved:
                os.environ["JEVETO_PASSWORD"] = saved

    def test_auth_enforced_with_password(self):
        saved = os.environ.get("JEVETO_PASSWORD")
        os.environ["JEVETO_PASSWORD"] = "pw-ep"
        try:
            c = self._client()
            self.assertEqual(c.get("/auth/status").json()["auth_required"], True)
            self.assertEqual(c.get("/agents").status_code, 401)
            self.assertEqual(c.post("/api/ask?capability=files", json={}).status_code, 401)
            self.assertEqual(c.get("/health").status_code, 200)     # 健康检查永远免鉴权
            self.assertEqual(c.post("/login", json={"password": "bad"}).status_code, 401)
            tok = c.post("/login", json={"password": "pw-ep"}).json()["token"]
            self.assertEqual(c.get("/agents", headers={"X-Token": tok}).status_code, 200)
            self.assertEqual(c.get("/agents", headers={"Authorization": f"Bearer {tok}"}).status_code, 200)
        finally:
            if saved is None:
                os.environ.pop("JEVETO_PASSWORD", None)
            else:
                os.environ["JEVETO_PASSWORD"] = saved


if __name__ == "__main__":
    unittest.main()
