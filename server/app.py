"""FastAPI 应用工厂：API 路由 + 前端静态托管（SPA fallback）"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api import config_api, files, history, tasks, uploads
from .config_store import PROJECT_ROOT

WEBUI_DIST = PROJECT_ROOT / "webui" / "dist"


_RULE_CN = {
    "Input should be greater than or equal to": "不得小于",
    "Input should be less than or equal to": "不得大于",
    "Field required": "不能为空",
    "String should match pattern": "格式不合法",
    "String should have at least": "长度至少",
    "Input should be a valid integer": "必须是整数",
    "Input should be a valid number": "必须是数字",
}


def _format_validation_errors(exc: RequestValidationError) -> str:
    """把 pydantic 校验错误翻成人话：哪个字段、什么规则、当前值"""
    lines = []
    for err in exc.errors():
        loc = " → ".join(str(x) for x in err.get("loc", []) if x not in ("body",))
        rule = err.get("msg", "")
        for en, cn in _RULE_CN.items():
            if en in rule:
                rule = rule.replace(en, cn)
                break
        lines.append(f"{loc or '请求体'} {rule}".strip())
    return "请求参数不合法：" + "；".join(lines)


def create_app() -> FastAPI:
    app = FastAPI(title="抖音视频智能解析工具", version="2.1")

    # 开发模式跨域（Vite dev server）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(tasks.router)
    app.include_router(config_api.router)
    app.include_router(history.router)
    app.include_router(files.router)
    app.include_router(uploads.router)

    @app.get("/api/health")
    def health():
        return {"ok": True}

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        """请求参数校验失败时返回人话错误，而不是 pydantic 的英文结构体"""
        return JSONResponse(status_code=422, content={"detail": _format_validation_errors(exc)})

    # ---- 前端静态托管（生产模式：webui/dist 构建产物） ----
    if WEBUI_DIST.exists():
        assets = WEBUI_DIST / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        async def spa(full_path: str):
            if full_path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not Found")
            candidate = (WEBUI_DIST / full_path).resolve()
            if candidate.is_relative_to(WEBUI_DIST.resolve()) and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(WEBUI_DIST / "index.html")

    return app


app = create_app()
