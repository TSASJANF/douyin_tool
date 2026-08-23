"""历史记录 API：浏览输出目录"""

from fastapi import APIRouter, HTTPException

from .. import config_store
from ..schemas import HistoryItem, HistoryFile

router = APIRouter(prefix="/api/history", tags=["history"])


def _safe_dir(dir_name: str):
    root = config_store.output_root()
    target = (root / dir_name).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(status_code=403, detail="非法路径")
    if not target.is_dir():
        raise HTTPException(status_code=404, detail="目录不存在")
    return target


@router.get("", response_model=list[HistoryItem])
def list_history():
    root = config_store.output_root()
    if not root.exists():
        return []

    items = []
    for d in root.iterdir():
        if not d.is_dir():
            continue
        # 内部工作目录（如 _uploads）不进历史列表
        if d.name.startswith(("_", ".")):
            continue
        try:
            files = [
                HistoryFile(
                    name=f.name,
                    size=f.stat().st_size,
                    mtime=f.stat().st_mtime,
                )
                for f in sorted(d.iterdir(), key=lambda x: x.name)
                if f.is_file()
            ]
        except OSError:
            continue
        items.append(HistoryItem(name=d.name, mtime=d.stat().st_mtime, files=files))

    items.sort(key=lambda x: x.mtime, reverse=True)
    return items


@router.get("/content")
def read_content(dir: str, file: str):
    """读取输出目录中的文本文件（正文.txt / info.txt 等）"""
    target_dir = _safe_dir(dir)
    path = (target_dir / file).resolve()
    if not path.is_relative_to(target_dir) or not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    if path.suffix.lower() not in (".txt", ".md", ".json"):
        raise HTTPException(status_code=400, detail="仅支持文本文件")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="gbk", errors="replace")
    return {"name": file, "content": text}
