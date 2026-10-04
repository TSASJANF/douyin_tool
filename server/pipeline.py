"""
处理流程（三个入口，CLI 与 WebUI 共用）

  run_pipeline  完整流程: 解析链接 → 下载视频 → 取解析直链 → MiMo解析 → 保存正文
  run_download  仅下载:   解析链接 → 下载视频 → 保存 info（不解析）
  run_parse     仅解析:   本地文件或视频直链 → MiMo解析 → 保存正文（不下载）

平台自动识别：粘贴抖音链接/口令或视频号分享链接都走同一套流程，
由 modules.platform.detect_platform 判断平台并选择对应下载器，无需用户选择。

on_event(type, data) 回调接收事件：
  - stage              {index, label}        阶段切换
  - log                {text}                日志
  - download_progress  {...}                 下载进度（透传自下载器）
  - analysis_delta     {reasoning|content}   解析增量文本（流式输出，思考过程/正文）
  - done               {title, content?, output_dir, dir, files}
失败时抛出 PipelineError。
"""

import asyncio
import time
from pathlib import Path
from typing import Callable, Optional

from modules.platform import PLATFORM_NAMES, create_downloader, detect_platform
from modules.video_analyzer import VideoAnalyzer
from .config_store import output_root

EventCallback = Callable[[str, dict], None]

# 阶段文案按平台区分：抖音要单独跟踪 720P 直链，视频号分享接口直接给出直链
STAGES = {
    "douyin": {
        "full": [
            {"index": 1, "label": "解析链接并下载1080P视频"},
            {"index": 2, "label": "获取720P直链"},
            {"index": 3, "label": "解析视频内容"},
        ],
        "download": [{"index": 1, "label": "解析链接并下载1080P视频"}],
    },
    "sph": {
        "full": [
            {"index": 1, "label": "解析视频号链接并下载视频"},
            {"index": 2, "label": "获取视频直链"},
            {"index": 3, "label": "解析视频内容"},
        ],
        "download": [{"index": 1, "label": "解析视频号链接并下载视频"}],
    },
}
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


def resolve_platform(url_text: str) -> str:
    """识别输入链接所属平台；无法识别时给出带原文的具体错误"""
    platform = detect_platform(url_text)
    if not platform:
        raise PipelineError(
            "无法识别的链接：本工具支持抖音链接/口令，以及视频号分享链接"
            "（如 https://weixin.qq.com/sph/xxxxxx）。"
            f"收到的输入：{url_text.strip()[:120]}"
        )
    return platform


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


def _attach_finish_info(payload: dict, analyzer) -> None:
    """把解析收尾信息（是否被截断、是否自动续写过）带出去，供前端透明展示"""
    payload["finish_reason"] = getattr(analyzer, "finish_reason", None)


def _done_payload(title: str, output_dir: Path, content: Optional[str]) -> dict:
    files = sorted(p.name for p in output_dir.iterdir() if p.is_file())
    return {
        "title": title,
        "content": content,
        "output_dir": str(output_dir),
        "dir": _dir_rel(output_dir),
        "files": files,
    }


async def _analyze_video(analyzer: VideoAnalyzer, analysis_url: str, platform: str,
                         video_path, on_event: EventCallback) -> Optional[str]:
    """调 MiMo 解析；视频号在直链解析失败时回退到已下载的本地文件重试一次"""
    content = await asyncio.to_thread(analyzer.analyze_remote_video, analysis_url)
    if content:
        return content

    local_file = Path(video_path) if video_path else None
    if platform != "sph" or not local_file or not local_file.is_file():
        return content

    # 视频号 CDN 直链可能限制外部服务抓取；直链失败时用已下载的本地文件（base64）兜底
    remote_error = analyzer.last_error or "MiMo API 未返回任何内容"
    on_event("log", {"text": f"直链解析未成功（{remote_error}），改用已下载的本地文件重试…"})
    content = await asyncio.to_thread(analyzer.analyze_local_video, str(local_file))
    if not content:
        raise PipelineError(
            f"直链解析失败：{remote_error}；"
            f"改用本地文件重试也失败：{analyzer.last_error or '未知原因'}"
        )
    return content


# ---------------- 完整流程 ----------------

async def run_pipeline(url_text: str, config: dict, on_event: EventCallback) -> dict:
    """
    完整流程：下载 → 直链 → 解析。

    返回: {"title", "content", "output_dir", "dir", "files"}
    """
    if is_image_content(url_text):
        raise PipelineError("检测到图片内容，本工具仅支持视频解析。")

    platform = resolve_platform(url_text)
    stages = STAGES[platform]["full"]
    forward: EventCallback = lambda t, d: on_event(t, d)

    # ---- 阶段 1: 下载 ----
    on_event("stage", stages[0])
    downloader = create_downloader(platform, config, on_event=forward)
    analyzer = VideoAnalyzer(config.get("mimo_api", {}), config.get("video_analysis", {}),
                             on_event=forward)

    download_result = await downloader.download(url_text)

    if not download_result:
        raise PipelineError(downloader.last_error or "下载失败：下载器未给出具体原因，请查看运行日志")

    video_path = download_result.get("video_1080p")
    output_dir: Path = download_result.get("output_dir")

    on_event("log", {"text": f"{PLATFORM_NAMES[platform]}视频已保存: {video_path}"})

    # ---- 阶段 2: 送解析的直链 ----
    on_event("stage", stages[1])

    analysis_url = await downloader.prepare_analysis_url(download_result)
    if not analysis_url:
        raise PipelineError(downloader.last_error or "获取视频直链失败，请重试")

    # ---- 阶段 3: MiMo 解析（同步阻塞调用，放入线程）----
    on_event("stage", stages[2])

    content = await _analyze_video(analyzer, analysis_url, platform, video_path, on_event)

    if not content:
        # 透传解析器的具体失败原因（HTTP 状态码/服务端信息/处理建议），不让用户猜
        raise PipelineError(analyzer.last_error or "视频解析失败：MiMo API 未返回任何内容")

    _save_content(output_dir, content)
    on_event("log", {"text": f"解析结果已保存到: {output_dir / '正文.txt'}"})

    payload = _done_payload(download_result.get("title", ""), output_dir, content)
    _attach_finish_info(payload, analyzer)
    on_event("done", payload)
    return payload


# ---------------- 仅下载 ----------------

async def run_download(url_text: str, config: dict, on_event: EventCallback) -> dict:
    """
    仅下载流程：解析链接并下载最高画质视频，不做 MiMo 解析。

    返回: {"title", "content": None, "output_dir", "dir", "files"}
    """
    if is_image_content(url_text):
        raise PipelineError("检测到图片内容，本工具仅支持视频。")

    platform = resolve_platform(url_text)

    on_event("stage", STAGES[platform]["download"][0])
    downloader = create_downloader(platform, config, on_event=lambda t, d: on_event(t, d))

    download_result = await downloader.download(url_text)

    if not download_result:
        raise PipelineError(downloader.last_error or "下载失败：下载器未给出具体原因，请查看运行日志")

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
        # 本模式要求的是可直接抓取的视频直链；分享页链接要走「视频解析/仅下载」
        platform = detect_platform(source)
        if platform:
            name = PLATFORM_NAMES.get(platform, platform)
            raise PipelineError(
                f"这是{name}的分享链接，不是可直接解析的视频直链。"
                f"请改用「视频解析」（下载并提取文案）或「仅下载」，本工具会自动识别链接类型"
            )
        on_event("log", {"text": f"解析视频直链: {source[:80]}..."})
        title = "直链解析"
        output_dir = output_root() / f"直链解析_{time.strftime('%Y%m%d_%H%M%S')}"
        output_dir.mkdir(parents=True, exist_ok=True)
        content = await asyncio.to_thread(analyzer.analyze_remote_video, source)

    if not content:
        # 透传解析器的具体失败原因（HTTP 状态码/服务端信息/处理建议），不让用户猜
        raise PipelineError(analyzer.last_error or "视频解析失败：MiMo API 未返回任何内容")

    _save_content(output_dir, content)
    on_event("log", {"text": f"解析结果已保存到: {output_dir / '正文.txt'}"})

    payload = _done_payload(title, output_dir, content)
    _attach_finish_info(payload, analyzer)
    on_event("done", payload)
    return payload
