"""本地文件上传 API（仅解析用）

采用原始流 PUT 上传（非 multipart，无需额外依赖），文件保存到
output/_uploads/<upload_id>/<安全文件名>，返回 upload_id 供创建解析任务引用。
"""

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from ..config_store import output_root
from modules.douyin_downloader import sanitize_filename

router = APIRouter(prefix="/api/uploads", tags=["uploads"])

MAX_UPLOAD_BYTES = 8 * 1024 * 1024 * 1024  # 8GB 上限保护
CHUNK = 1024 * 1024


def uploads_root() -> Path:
    d = output_root() / "_uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def resolve_upload(upload_id: str) -> Path | None:
    """upload_id → 其中唯一的文件路径；无效返回 None"""
    if not upload_id or not all(c.isalnum() for c in upload_id):
        return None
    d = uploads_root() / upload_id
    if not d.is_dir():
        return None
    files = [f for f in d.iterdir() if f.is_file()]
    return files[0] if len(files) == 1 else None


@router.put("")
async def upload(request: Request, filename: str = Query(..., min_length=1)):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="文件超过 8GB 上限")

    upload_id = uuid.uuid4().hex[:12]
    dest_dir = uploads_root() / upload_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(filename)
    dest = dest_dir / safe_name

    size = 0
    try:
        with open(dest, "wb") as f:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件超过 8GB 上限")
                f.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="上传内容为空")
    except HTTPException:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise
    except OSError as e:
        shutil.rmtree(dest_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"写入失败: {e}")

    return {"upload_id": upload_id, "filename": safe_name, "size": size}
