"""视频号视频下载器：解析分享链接 → 下载直链 → 写 info.txt。

落盘/进度/重试复用 BaseDownloader；分享链接的解析交给 sph_resolver
（内部流程移植自 wx_channels_download，也可通过 sph.api_base 直接复用该项目）。
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from .base_downloader import BaseDownloader, sanitize_filename
from .sph_resolver import SphResolver, SphResolverError, SphVideoInfo

# 视频号 CDN（finder.video.qq.com）实测不校验 Referer，带上只为更贴近真实播放环境
SPH_REQUEST_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"),
    "Referer": "https://channels.weixin.qq.com/",
    "Accept": "*/*",
}

# 视频号视频比抖音大一些，给足超时
DOWNLOAD_TIMEOUT = 300.0


class SphDownloader(BaseDownloader):
    """视频号下载器"""

    platform = "sph"

    def __init__(self, download_config: dict, sph_config: Optional[dict] = None,
                 on_event=None):
        super().__init__(download_config, on_event=on_event)
        self.sph_config = sph_config or {}
        self.resolver = SphResolver(self.sph_config, on_event=on_event)

    async def download(self, url_text: str) -> Optional[Dict[str, Any]]:
        """
        解析并下载视频号视频

        返回: {
            "video_1080p": Path, "output_dir": Path, "title": str,
            "platform": "sph", "result": dict, "analysis_url": str
        } 或 None
        """
        self.last_error = None
        self._emit_log("正在解析视频号分享链接...")

        try:
            info = await self.resolver.resolve(url_text)
        except SphResolverError as e:
            self.last_error = str(e)
            self._emit_log(f"错误: {self.last_error}")
            return None
        except Exception as e:  # 兜底：不让未预期异常吞掉具体原因
            self.last_error = f"解析视频号链接失败: {type(e).__name__}: {e}"
            self._emit_log(f"错误: {self.last_error}")
            return None

        folder_name = self._folder_name(info)
        output_dir = self.output_dir / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        self._emit_log(f"标题: {info.title}")
        self._emit_log(f"作者: {info.author or '未知'}")

        video_path = output_dir / f"{folder_name}_原画.mp4"

        if video_path.exists():
            self._emit_log(f"视频已存在: {video_path.name}")
        else:
            self._emit_log("正在下载视频...")
            # 失败原因已记入 last_error 并输出日志
            if not await self._download_file(info.video_url, video_path,
                                             timeout=DOWNLOAD_TIMEOUT,
                                             headers=SPH_REQUEST_HEADERS):
                return None

        self._write_info(output_dir, info)

        return {
            "video_1080p": video_path,
            "output_dir": output_dir,
            "title": info.title,
            "platform": "sph",
            "analysis_url": info.video_url,
            "result": {
                "title": info.title,
                "author": {"nickname": info.author},
                "media": {"type": "video", "url": info.video_url},
                "resolved_url": info.share_url,
                "create_time": info.create_time,
            },
        }

    async def prepare_analysis_url(self, download_result: dict) -> Optional[str]:
        """视频号分享接口直接给出可用的 CDN 直链，无需再跟踪 302"""
        self.last_error = None
        url = (download_result or {}).get("analysis_url") or ""
        if not url:
            self.last_error = ("未找到可解析的视频直链：视频号接口没有返回 videoUrl，"
                              "请重试或换一个视频")
            return None
        self._emit_log(f"视频直链: {url[:80]}...")
        return url

    # ---------------- 内部 ----------------

    def _folder_name(self, info: SphVideoInfo) -> str:
        """输出目录名：优先用文案描述；描述为空时补 id 后缀避免同名覆盖"""
        folder_name = sanitize_filename(info.title)
        if not info.description.strip():
            suffix = (info.export_id.rsplit("/", 1)[-1][:8]
                      or time.strftime("%Y%m%d%H%M%S"))
            folder_name = sanitize_filename(f"{folder_name}_{suffix}")
        return folder_name

    def _write_info(self, output_dir: Path, info: SphVideoInfo):
        info_path = output_dir / "info.txt"
        with open(info_path, "w", encoding="utf-8") as f:
            f.write(f"标题: {info.title}\n")
            f.write(f"作者: {info.author or '未知'}\n")
            f.write(f"平台: 视频号\n")
            f.write(f"链接: {info.share_url}\n")
            f.write("类型: video\n")
            if info.export_id:
                f.write(f"内容ID: {info.export_id}\n")

            if info.create_time:
                try:
                    dt = datetime.fromtimestamp(info.create_time, tz=timezone.utc)
                    f.write(f"发布时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
                except (OSError, OverflowError, ValueError):
                    pass

            for label, value in info.stats.items():
                f.write(f"{label}数: {value}\n")

            if info.description:
                f.write(f"描述: {info.description[:100]}\n")
