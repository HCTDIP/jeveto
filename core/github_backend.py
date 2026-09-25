#!/usr/bin/env python3
"""真 PR 后端：把 fork → 建分支+提交 → 开 PR → 读 CI 全流程接到 GitHub API。

与 `MockPipelineBackend` **接口完全一致**（fork/commit_fix/open_pr/check_ci 同名同返回形状），
所以可以直接替换 —— 这是"零模型费"的那条线：全是 GitHub API，不花一分钱模型钱。

环境：
    GITHUB_TOKEN  必填（repo scope；fork 别人的仓库还需要 public_repo）
    GITHUB_BASE   可选，默认 https://api.github.com（给 GitHub Enterprise / GitLab 留口子）

用法（测试沙盒）：
    GITHUB_TOKEN=... python3 -m core.github_backend --org HCTDIP --repo pipeline-sandbox
"""
import base64
import json
import os
import urllib.error
import urllib.request

API = os.environ.get("GITHUB_BASE", "https://api.github.com")
UA = "jeveto-pipeline/0.2 (+https://github.com/HCTDIP/jeveto)"


class GitHubPipelineBackend:
    """真后端。每个方法都做一次真实 HTTP 调用，返回形状与 Mock 一致。"""

    def __init__(self, token: str = None, api: str = API):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        if not self.token:
            raise RuntimeError("GITHUB_TOKEN 未设置：真 PR 后端需要它的 repo scope")
        self.api = api.rstrip("/")
        self.calls = []

    # ---------- HTTP ----------
    def _req(self, method: str, path: str, body: dict = None, ok=(200, 201, 204)):
        url = path if path.startswith("http") else f"{self.api}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": UA,
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                raw = r.read().decode() or "{}"
                return json.loads(raw), r.status
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="ignore")[:300]
            raise RuntimeError(f"GitHub {method} {path} -> {e.code}: {detail}")

    # ---------- 管线四步（与 Mock 同名） ----------
    def fork(self, rec: dict) -> dict:
        """真 fork 到 token 名下（若就是自己的仓，GitHub 直接返回原仓）。"""
        owner, repo = rec["org"], rec["repo"]
        d, _ = self._req("POST", f"/repos/{owner}/{repo}/forks")
        self.calls.append(("fork", f"{owner}/{repo}"))
        return {"fork_url": d.get("html_url", f"https://github.com/{owner}/{repo}"),
                "clone_url": d.get("clone_url")}

    def commit_fix(self, rec: dict, tree: dict = None) -> dict:
        """在 fork/本仓建一个 fix 分支并提交改动（默认写一个说明文件，可传入 tree={path: content}）。"""
        owner, repo = rec["org"], rec["repo"]     # 同仓内 PR（沙盒模式）；真 fork 时把 owner 换成 token 用户
        base = rec.get("base", "main")
        issue = (rec.get("issue_url") or "").rstrip("/").split("/")[-1] or "auto"
        branch = rec.get("branch") or f"fix/{repo}-{issue}"

        ref, _ = self._req("GET", f"/repos/{owner}/{repo}/git/ref/heads/{base}")
        base_sha = ref["object"]["sha"]
        try:
            self._req("POST", f"/repos/{owner}/{repo}/git/refs",
                      {"ref": f"refs/heads/{branch}", "sha": base_sha})
        except RuntimeError as e:
            if "already exists" not in str(e) and "422" not in str(e):
                raise

        files = tree or {"PIPELINE.md": f"# pipeline touch\n\nissue: {rec.get('issue_url') or 'n/a'}\n"}
        for path, content in files.items():
            body = {"message": f"fix: {path} (auto pipeline)", "branch": branch,
                    "content": base64.b64encode(content.encode()).decode()}
            existing, _ = self._req1("GET", f"/repos/{owner}/{repo}/contents/{path}?ref={branch}")
            if existing and existing.get("sha"):
                body["sha"] = existing["sha"]
            self._req("PUT", f"/repos/{owner}/{repo}/contents/{path}", body)

        self.calls.append(("commit_fix", branch))
        return {"branch": branch, "base": base, "head_owner": owner}

    def _req1(self, method, path, body=None):
        """允许 404 的一次请求（用于判断文件是否已存在）。"""
        try:
            return self._req(method, path, body), True
        except RuntimeError as e:
            if "404" in str(e):
                return None, False
            raise

    def open_pr(self, rec: dict, branch: str = None, title: str = None) -> dict:
        owner, repo = rec["org"], rec["repo"]
        head = branch or f"{rec['org']}:{rec.get('branch')}"
        if ":" not in head and not head.startswith(rec["org"]):
            head = f"{rec['org']}:{head}"
        d, _ = self._req("POST", f"/repos/{owner}/{repo}/pulls", {
            "title": title or f"[auto] {rec.get('issue_url') or repo}",
            "head": head, "base": rec.get("base", "main"),
            "body": "Automated by jeveto GitHubPipelineBackend (fork → commit_fix → open_pr → check_ci).",
        })
        self.calls.append(("open_pr", d["html_url"]))
        return {"pr_url": d["html_url"], "pr_number": d["number"], "head_sha": (d.get("head") or {}).get("sha")}

    def check_ci(self, pr_url: str, head_sha: str = None) -> dict:
        """读 PR 的 CI 状态（无 CI 时返回 pending，不假装 pass —— mock 那种"写死 pass"是自欺）。"""
        if head_sha is None:
            owner_repo = "/".join(pr_url.split("/")[3:5])
            num = pr_url.rstrip("/").split("/")[-1]
            pr, _ = self._req("GET", f"/repos/{owner_repo}/pulls/{num}")
            head_sha = (pr.get("head") or {}).get("sha")
            owner_repo = "/".join(pr_url.split("/")[3:5])
        else:
            owner_repo = "/".join(pr_url.split("/")[3:5])
        runs, _ = self._req("GET", f"/repos/{owner_repo}/commits/{head_sha}/check-runs")
        checks = runs.get("check_runs", [])
        if not checks:
            status, comments = "pending(no checks configured)", []
        else:
            concl = [c.get("conclusion") for c in checks]
            if any(c == "failure" for c in concl):
                status = "fail"
            elif all(c == "success" for c in concl):
                status = "pass"
            else:
                status = "pending"
            comments = [f"{c['name']}: {c.get('conclusion')}" for c in checks]
        self.calls.append(("check_ci", pr_url))
        return {"ci_status": status, "review_comments": comments, "head_sha": head_sha}


def real_or_mock(rec: dict = None):
    """选后端：有 GITHUB_TOKEN 就用真的，否则退回 mock（本地开发/TDD）。"""
    from .agents_registry import MockPipelineBackend
    return GitHubPipelineBackend() if os.environ.get("GITHUB_TOKEN") else MockPipelineBackend()


def _selftest(org: str, repo: str):
    """端到端自测：真开一个 PR，核对 URL 真的存在。"""
    be = GitHubPipelineBackend()
    rec = {"org": org, "repo": repo, "handle": org, "issue_url": f"https://github.com/{org}/{repo}/issues/1"}
    pr = be.open_pr  # noqa: F841 (readability)
    be.fork(rec)
    c = be.commit_fix(rec, tree={"PIPELINE.md": "# auto pipeline touch\n"})
    out = be.open_pr(rec, branch=c["branch"])
    ci = be.check_ci(out["pr_url"], head_sha=out.get("head_sha"))
    print(json.dumps({"pr_url": out["pr_url"], "pr_number": out["pr_number"],
                      "branch": c["branch"], "ci_status": ci["ci_status"], "calls": be.calls},
                     ensure_ascii=False, indent=2))
    # R3：read-back —— 用 API 确认 PR 真的在
    pr_view, _ = be._req("GET", f"/repos/{org}/{repo}/pulls/{out['pr_number']}")
    assert pr_view["number"] == out["pr_number"], "PR read-back 失败"
    print(f"✅ read-back OK: PR #{pr_view['number']} state={pr_view['state']} url={pr_view['html_url']}")
    return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="真 PR 后端自测")
    ap.add_argument("--org", default="HCTDIP")
    ap.add_argument("--repo", default="pipeline-sandbox")
    a = ap.parse_args()
    _selftest(a.org, a.repo)
