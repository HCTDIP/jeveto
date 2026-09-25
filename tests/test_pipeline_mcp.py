"""真 PR 后端 + MCP 接线的离线测试（零外呼，CI 可跑）。"""
import os
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.github_backend import GitHubPipelineBackend, real_or_mock  # noqa: E402
from core.mcp_agent import parse_mcp_endpoint  # noqa: E402


class TestMcpEndpoint(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_mcp_endpoint("mcp://filesystem/list_directory"),
                         ("filesystem", "list_directory"))
        self.assertEqual(parse_mcp_endpoint("mcp://github/create_pull_request"),
                         ("github", "create_pull_request"))
        self.assertIsNone(parse_mcp_endpoint("https://api.example.com/x"))
        self.assertIsNone(parse_mcp_endpoint(None))

    def test_bad_shape_raises(self):
        with self.assertRaises(Exception):
            parse_mcp_endpoint("mcp://filesystem-only")


class StubBackend(GitHubPipelineBackend):
    """把 HTTP 层换成脚本化响应 —— 测试四步管线的编排，不出网。"""

    def __init__(self):
        os.environ["GITHUB_TOKEN"] = "stub"
        super().__init__(token="stub")
        self.sent = []

    def _req(self, method, path, body=None, ok=(200, 201, 204)):
        self.sent.append((method, path, body))
        if "/forks" in path:
            return {"html_url": "https://github.com/stub/pipeline-sandbox"}, 201
        if "/git/ref/heads/" in path:
            return {"object": {"sha": "deadbeef"}}, 200
        if path.endswith("/git/refs"):
            return {"ref": body["ref"]}, 201
        if "/contents/" in path and method == "GET":
            raise RuntimeError("GitHub GET /contents -> 404: not found")
        if "/contents/" in path:
            return {"commit": {"sha": "cafe"}}, 201
        if path.endswith("/pulls") and method == "POST":
            return {"html_url": "https://github.com/stub/pipeline-sandbox/pull/7",
                    "number": 7, "head": {"sha": "cafe"}}, 201
        if "/check-runs" in path:
            return {"check_runs": [{"name": "ci", "conclusion": "success"}]}, 200
        raise AssertionError(f"未预期的调用 {method} {path}")


class TestRealPipelineBackend(unittest.TestCase):
    def test_four_steps_wire_up(self):
        be = StubBackend()
        rec = {"org": "stub", "repo": "pipeline-sandbox", "handle": "stub",
               "issue_url": "https://github.com/stub/pipeline-sandbox/issues/1"}
        be.fork(rec)
        c = be.commit_fix(rec)
        self.assertTrue(c["branch"].startswith("fix/"))
        pr = be.open_pr(rec, branch=c["branch"])
        self.assertEqual(pr["pr_number"], 7)
        ci = be.check_ci(pr["pr_url"], head_sha=pr["head_sha"])
        self.assertEqual(ci["ci_status"], "pass")
        self.assertEqual([s[0] for s in be.calls], ["fork", "commit_fix", "open_pr", "check_ci"])

    def test_check_ci_honest_when_no_checks(self):
        be = StubBackend()

        def no_checks(method, path, body=None, ok=(200, 201, 204)):
            return {"check_runs": []}, 200
        be._req = no_checks
        out = be.check_ci("https://github.com/stub/pipeline-sandbox/pull/7", head_sha="cafe")
        self.assertEqual(out["ci_status"], "pending(no checks configured)")   # 绝不假装 pass

    def test_requires_token(self):
        # 显式清掉环境变量：否则会回落到 env 里的 token，测不出"必须有 token"这条
        saved = os.environ.pop("GITHUB_TOKEN", None)
        try:
            with self.assertRaises(RuntimeError):
                GitHubPipelineBackend(token="")
        finally:
            if saved:
                os.environ["GITHUB_TOKEN"] = saved


class TestBackendSelection(unittest.TestCase):
    """四种组合全测，且完全不依赖外部环境（CI 里也确定）。"""

    KEYS = ("JEVETO_PIPELINE", "GITHUB_TOKEN")

    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in self.KEYS}

    def tearDown(self):
        for k in self.KEYS:
            os.environ.pop(k, None)
            if self.saved.get(k):
                os.environ[k] = self.saved[k]

    def _snap(self):
        return {k: v for k, v in os.environ.items() if "JEVETO" in k or "GITHUB_TOKEN" == k}

    def test_真开关四种组合(self):
        from core.agents_registry import MockPipelineBackend

        # 1) 什么都不设 → mock
        self.assertIsInstance(real_or_mock(), MockPipelineBackend, self._snap())
        # 2) 只有 token、没开关 → 仍 mock（绝不"有 token 就偷偷变脸"）
        os.environ["GITHUB_TOKEN"] = "stub"
        self.assertIsInstance(real_or_mock(), MockPipelineBackend, self._snap())
        # 3) 开关=real + token → 真后端
        os.environ["JEVETO_PIPELINE"] = "real"
        self.assertIsInstance(real_or_mock(), GitHubPipelineBackend, self._snap())
        # 4) 开关=real 但没 token → 退回 mock（不硬闯）
        os.environ.pop("GITHUB_TOKEN")
        self.assertIsInstance(real_or_mock(), MockPipelineBackend, self._snap())


if __name__ == "__main__":
    unittest.main()
