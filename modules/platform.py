"""平台自动识别与下载器分发。

用户只粘贴链接，不需要选平台：这里按链接域名判断是抖音还是视频号，
并返回对应的下载器实例。新增平台只需在这里加一条判断。
"""

from __future__ import annotations

from typing import Optional

from .base_downloader import EventCallback
from .douyin_downloader import DouyinDownloader
from .douyin_resolver.input_parser import extract_urls, is_douyin_url
from .sph_downloader import SphDownloader
from .sph_resolver import is_sph_url

PLATFORM_NAMES = {"douyin": "抖音", "sph": "视频号"}


def detect_platform(text: str) -> str:
    """判断输入属于哪个平台。

    返回 "douyin" / "sph"；输入里带了链接但都不是已知平台时返回 ""（由调用方报错）。
    纯文本（如抖音分享口令"7.89 复制打开抖音…"）按抖音处理，
    让抖音解析器给出它自己的具体错误，保持原有行为不变。
    """
    text = (text or "").strip()
    urls = extract_urls(text)
    if any(is_sph_url(u) for u in urls):
        return "sph"
    if any(is_douyin_url(u) for u in urls):
        return "douyin"
    if urls or text.startswith(("http://", "https://")):
        return ""
    return "douyin"


def create_downloader(platform: str, config: dict, on_event: EventCallback):
    """按平台创建下载器；两者共用下载目录/重试配置（douyin 段）"""
    download_config = config.get("douyin", {})
    if platform == "sph":
        return SphDownloader(download_config, config.get("sph", {}), on_event=on_event)
    return DouyinDownloader(download_config, on_event=on_event)
