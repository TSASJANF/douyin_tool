"""FastAPI 应用工厂：API 路由 + 前端静态托管（SPA fallback）"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import config_api, files, history, tasks, uploads
from .config_store import PROJECT_ROOT

WEBUI_DIST = PROJECT_ROOT / "webui" / "dist"


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
