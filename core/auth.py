#!/usr/bin/env python3
"""最小可用鉴权：单用户密码 → 签名 token（零依赖，HMAC-SHA256）。

为什么需要：jeveto 一旦放到公网常驻，**每个请求都在烧 Jev 额度**（真钱）。
没有鉴权 = 把钱包挂在门口。加一层最简登录，够挡住"路人调用"。

设计取舍（故意简单）：
  · 单用户够用（我们只有一个人用），不做用户表、不做 OAuth
  · 密码只从环境变量读（`JEVETO_PASSWORD`），**不进代码、不进仓库**
  · **没设密码 = 鉴权关闭**（本地开发/CI 行为不变，不会被登录墙挡住）
  · token = HMAC 签名的 `过期时间戳`，无状态、可重启、不依赖数据库
  · 同时接受 `Authorization: Bearer <t>` 和 `X-Token: <t>`（浏览器取用后者更省事）
"""
import base64
import hashlib
import hmac
import os
import time

DEFAULT_TTL = int(os.environ.get("JEVETO_TOKEN_TTL", "43200"))   # 12 小时


def password() -> str:
    return os.environ.get("JEVETO_PASSWORD", "") or ""


def auth_required() -> bool:
    return bool(password())


def _secret() -> bytes:
    # 优先独立密钥；没有就用密码派生（简单、够用、零配置）
    s = os.environ.get("JEVETO_SECRET") or password() or "insecure-dev"
    return hashlib.sha256(f"jeveto::{s}".encode()).digest()


def _sign(msg: str) -> str:
    return hmac.new(_secret(), msg.encode(), hashlib.sha256).hexdigest()[:32]


def issue_token(ttl: int = None) -> dict:
    exp = int(time.time()) + (ttl or DEFAULT_TTL)
    payload = f"{exp}"
    token = base64.urlsafe_b64encode(f"{payload}.{_sign(payload)}".encode()).decode()
    return {"token": token, "expires_in": ttl or DEFAULT_TTL, "expires_at": exp}


def verify_token(token: str) -> bool:
    if not token:
        return False
    try:
        raw = base64.urlsafe_b64decode(token.encode()).decode()
        exp_s, sig = raw.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(exp_s)):
            return False
        return int(exp_s) > int(time.time())
    except Exception:
        return False


def check_password(given: str) -> bool:
    p = password()
    return bool(p) and hmac.compare_digest(given or "", p)


# ---------- FastAPI 依赖 ----------
from fastapi import Header, HTTPException   # noqa: E402


def require_auth(authorization: str = Header(default=None), x_token: str = Header(default=None)):
    """FastAPI 依赖：未设密码 → 放行（开发模式）；设了密码 → 必须带合法 token。

    ⚠️ 必须写成**依赖函数本体**，不能写成"返回内层函数的工厂" ——
    否则 FastAPI 只会把外层参数当 query 参数，内层闭包用默认值执行，永远 401（本仓踩过）。
    """
    if not auth_required():
        return True
    token = x_token or ""
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if verify_token(token):
        return True
    raise HTTPException(status_code=401, detail="未登录或登录已过期：请先 POST /login 取 token",
                        headers={"WWW-Authenticate": "Bearer"})
