"""文件 API：下载与 Range 流式播放（限制在输出目录内）"""

import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from .. import config_store

router = APIRouter(prefix="/api/files", tags=["files"])

CHUNK_SIZE = 1024 * 512  # 512KB


def _safe_file(dir: str, file: str) -> Path:
    root = config_store.output_root()
    target = (root / dir / file).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return target


@router.get("/download")
def download(dir: str, file: str):
    path = _safe_file(dir, file)
    return FileResponse(path, filename=path.name)


@router.get("/stream")
async def stream(dir: str, file: str, request: Request):
    """视频/音频在线播放，支持 HTTP Range（拖动进度条）"""
    path = _safe_file(dir, file)
    size = path.stat().st_size
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    range_header = request.headers.get("range", "")
    match = re.match(r"bytes=(\d*)-(\d*)", range_header)

    if match and (match.group(1) or match.group(2)):
        start = int(match.group(1) or 0)
        end = int(match.group(2)) if match.group(2) else size - 1
        end = min(end, size - 1)
        if start > end or start >= size:
            raise HTTPException(status_code=416, detail="Range 不可用")

        length = end - start + 1

        def iter_file():
            with open(path, "rb") as f:
                f.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = f.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk

        return StreamingResponse(
            iter_file(),
            status_code=206,
            media_type=mime,
            headers={
                "Content-Range": f"bytes {start}-{end}/{size}",
                "Accept-Ranges": "bytes",
                "Content-Length": str(length),
            },
        )

    return FileResponse(path, media_type=mime, headers={"Accept-Ranges": "bytes"})
