"""
处理流程（三个入口，CLI 与 WebUI 共用）

  run_pipeline  完整流程: 下载1080P → 获取720P直链 → MiMo解析 → 保存正文
  run_download  仅下载:   解析链接 → 下载1080P → 保存 info（不解析）
  run_parse     仅解析:   本地文件或视频直链 → MiMo解析 → 保存正文（不下载）

on_event(type, data) 回调接收事件：
  - stage              {index, label}        阶段切换
  - log                {text}                日志
  - download_progress  {...}                 下载进度（透传自下载器）
  - done               {title, content?, output_dir, dir, files}
失败时抛出 PipelineError。
"""

import asyncio
import time
from pathlib import Path
from typing import Callable, Optional

from modules.douyin_downloader import DouyinDownloader
from modules.video_analyzer import VideoAnalyzer
from .config_store import output_root

EventCallback = Callable[[str, dict], None]

STAGES_FULL = [
    {"index": 1, "label": "解析链接并下载1080P视频"},
    {"index": 2, "label": "获取720P直链"},
    {"index": 3, "label": "解析视频内容"},
]
STAGES_DOWNLOAD = [{"index": 1, "label": "解析链接并下载1080P视频"}]
STAGES_PARSE = [{"index": 1, "label": "解析视频内容"}]


class PipelineError(Exception):
    """流程错误，message 面向用户"""


def is_image_content(url_text: str) -> bool:
    image_extensions = ['.jpg', '.jpeg', '.png', '.webp', '.gif', '.bmp']
    url_lower = url_text.lower()
    for ext in image_extensions:
        if ext in url_lower:
            return True
    return False


def _dir_rel(output_dir: Path) -> str:
    """输出目录相对于 output 根的 posix 路径（供前端文件接口使用）"""
    root = output_root()
    try:
        return output_dir.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return output_dir.name


def _save_content(output_dir: Path, content: str) -> Path:
    content_file = output_dir / "正文.txt"
    with open(content_file, "w", encoding="utf-8") as f:
        f.write("\n" + content)
    return content_file


def _done_payload(title: str, output_dir: Path, content: Optional[str]) -> dict:
    files = sorted(p.name for p in output_dir.iterdir() if p.is_file())
    return {
        "title": title,
        "content": content,
        "output_dir": str(output_dir),
        "dir": _dir_rel(output_dir),
        "files": files,
    }


# ---------------- 完整流程 ----------------

async def run_pipeline(url_text: str, config: dict, on_event: EventCallback) -> dict:
    """
    完整流程：下载 → 直链 → 解析。

    返回: {"title", "content", "output_dir", "dir", "files"}
    """
    if is_image_content(url_text):
        raise PipelineError("检测到图片内容，本工具仅支持视频解析。")

    forward: EventCallback = lambda t, d: on_event(t, d)

    # ---- 阶段 1: 下载 ----
    on_event("stage", STAGES_FULL[0])
    douyin = DouyinDownloader(config.get("douyin", {}), on_event=forward)
    analyzer = VideoAnalyzer(config.get("mimo_api", {}), config.get("video_analysis", {}),
                             on_event=forward)

    download_result = await douyin.download(url_text)

    if not download_result:
        raise PipelineError(douyin.last_error or "下载失败。")

    video_1080p = download_result.get("video_1080p")
    output_dir: Path = download_result.get("output_dir")

    on_event("log", {"text": f"1080P视频已保存: {video_1080p}"})

    # ---- 阶段 2: 720P 直链 ----
    on_event("stage", STAGES_FULL[1])

    # 从下载结果中获取qualities，避免重复解析
    result = download_result.get("result", {})
    qualities = result.get("media", {}).get("qualities", [])

    url_720p = None
    for q in qualities:
        if "720" in q.get("quality_name", ""):
            url_720p = q.get("url")
            break

    if not url_720p:
        raise PipelineError("未找到720P直链")

    on_event("log", {"text": f"720P接口URL: {url_720p[:80]}..."})

    real_direct_url = await douyin.get_real_direct_url(url_720p)

    if not real_direct_url:
        raise PipelineError("获取真正直链失败")

    on_event("log", {"text": f"720P真正直链: {real_direct_url[:80]}..."})

    # ---- 阶段 3: MiMo 解析（同步阻塞调用，放入线程）----
    on_event("stage", STAGES_FULL[2])

    content = await asyncio.to_thread(analyzer.analyze_remote_video, real_direct_url)

    if not content:
        raise PipelineError("视频解析失败。")

    _save_content(output_dir, content)
    on_event("log", {"text": f"解析结果已保存到: {output_dir / '正文.txt'}"})

    payload = _done_payload(download_result.get("title", ""), output_dir, content)
    on_event("done", payload)
    return payload


# ---------------- 仅下载 ----------------

async def run_download(url_text: str, config: dict, on_event: EventCallback) -> dict:
    """
    仅下载流程：解析链接并下载1080P，不做 MiMo 解析。

    返回: {"title", "content": None, "output_dir", "dir", "files"}
    """
    if is_image_content(url_text):
        raise PipelineError("检测到图片内容，本工具仅支持视频。")

    on_event("stage", STAGES_DOWNLOAD[0])
    douyin = DouyinDownloader(config.get("douyin", {}), on_event=lambda t, d: on_event(t, d))

    download_result = await douyin.download(url_text)

    if not download_result:
        raise PipelineError(douyin.last_error or "下载失败。")

    on_event("log", {"text": f"下载完成: {download_result.get('video_1080p')}"})

    payload = _done_payload(download_result.get("title", ""),
                            download_result.get("output_dir"), None)
    on_event("done", payload)
    return payload


# ---------------- 仅解析 ----------------

async def run_parse(source_type: str, source: str, config: dict, on_event: EventCallback) -> dict:
    """
    仅解析流程：本地文件或视频直链 → MiMo 解析 → 保存正文。

    Args:
        source_type: "file"（source 为服务端绝对路径）或 "url"（source 为视频直链）
    返回: {"title", "content", "output_dir", "dir", "files"}
    """
    analyzer = VideoAnalyzer(config.get("mimo_api", {}), config.get("video_analysis", {}),
                             on_event=lambda t, d: on_event(t, d))

    on_event("stage", STAGES_PARSE[0])

    if source_type == "file":
        path = Path(source)
        if not path.is_file():
            raise PipelineError(f"文件不存在: {path.name}")
        on_event("log", {"text": f"解析本地文件: {path.name}"})
        title = path.stem
        output_dir = path.parent  # 正文保存在视频同目录
        content = await asyncio.to_thread(analyzer.analyze_local_video, str(path))
    else:
        if not source.startswith(("http://", "https://")):
            raise PipelineError("请提供 http(s) 视频直链")
        on_event("log", {"text": f"解析视频直链: {source[:80]}..."})
        title = "直链解析"
        output_dir = output_root() / f"直链解析_{time.strftime('%Y%m%d_%H%M%S')}"
        output_dir.mkdir(parents=True, exist_ok=True)
        content = await asyncio.to_thread(analyzer.analyze_remote_video, source)

    if not content:
        raise PipelineError("视频解析失败。")

    _save_content(output_dir, content)
    on_event("log", {"text": f"解析结果已保存到: {output_dir / '正文.txt'}"})

    payload = _done_payload(title, output_dir, content)
    on_event("done", payload)
    return payload
