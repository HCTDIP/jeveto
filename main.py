import os

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from core import models, database
from api.routes import router
from core.auth import auth_required, check_password, issue_token, require_auth

# Initialize database
models.Base.metadata.create_all(bind=database.engine)

# 启动时幂等注册 MCP 工具 agent —— 否则干净部署是个空壳（任何 capability 都 no_agent）。
# 用显式开关（部署时由 Dockerfile 置 1），避免影响本地测试与 CI 的既有断言。
if os.environ.get("JEVETO_MCP_AGENTS") == "1":
    from core.mcp_agent import register_mcp_agents  # noqa: E402

    with database.SessionLocal() as _db:
        register_mcp_agents(_db)

app = FastAPI(title="Jeveto")

app.include_router(router, prefix="/api")

@app.get("/")
def read_root():
    return FileResponse(path="static/index.html")

@app.get("/health")
def health_check():
    return {"status": "running", "version": "0.2.0"}

@app.post("/login")
def login(payload: dict):
    """单用户登录：{password} → {token}。未设 JEVETO_PASSWORD 时鉴权关闭。"""
    from fastapi import HTTPException
    if not auth_required():
        return {"auth_required": False, "token": "", "note": "服务端未设 JEVETO_PASSWORD，鉴权关闭"}
    if not check_password((payload or {}).get("password", "")):
        raise HTTPException(status_code=401, detail="密码错误")
    return {"auth_required": True, **issue_token()}


@app.get("/auth/status")
def auth_status():
    return {"auth_required": auth_required()}


@app.get("/agents")
def list_agents(db: Session = Depends(database.get_db), _=Depends(require_auth)):
    return db.query(models.Agent).all()

app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    # 云平台会注入 $PORT；本地不设就用 8000
    import os
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
