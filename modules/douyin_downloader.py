"""
抖音视频下载模块
提取自原抖音下载部分的逻辑

支持事件回调：构造时传入 on_event(type, data) 可将日志与下载进度转发给
外部（如 WebUI）；不传时保持原有 print 输出，CLI 行为不变。
"""

import os
import re
import sys
import asyncio
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, Callable
import httpx

from .douyin_resolver import parse_input, resolve_url, fetch_work_info, BROWSER_HEADERS

EventCallback = Callable[[str, dict], None]


def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\n\r]', '', name)
    name = name.strip(' .')
    if len(name) > 80:
        name = name[:80]
    return name.strip() or "untitled"


class DouyinDownloader:
    """抖音视频下载器"""

    def __init__(self, config: dict, on_event: Optional[EventCallback] = None):
        self.config = config
        self.on_event = on_event
        self.output_dir = Path(__file__).parent.parent / config.get("download_dir", "output")
        self.max_retry = config.get("max_retry", 3)
        self.video_quality = config.get("video_quality", "highest")

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _emit_log(self, text: str):
        """输出日志：有回调时发事件，否则打印"""
        if self.on_event:
            self.on_event("log", {"text": text})
        else:
            print(text)

    def _emit_progress(self, data: dict):
        """输出发下载进度：有回调时发事件，否则打印单行刷新"""
        if self.on_event:
            self.on_event("download_progress", data)
        else:
            if data.get("total_mb"):
                line = (
                    f"\r下载进度: {data['percent']:.1f}% "
                    f"({data['downloaded_mb']:.1f}/{data['total_mb']:.1f} MB) "
                    f"| 速度: {data.get('speed_str', '-')} "
                    f"| 剩余: {data.get('eta', '-')}    "
                )
            else:
                line = f"\r已下载: {data['downloaded_mb']:.1f} MB    "
            print(line, end="", flush=True)

    def _sanitize_filename(self, name: str) -> str:
        """清理文件名，移除非法字符"""
        return sanitize_filename(name)

    async def _resolve_douyin_link(self, url_text: str) -> Optional[Dict[str, Any]]:
        """解析抖音链接，获取视频信息"""
        try:
            clean_url = parse_input(url_text)

            async with httpx.AsyncClient(
                timeout=15.0,
                headers=BROWSER_HEADERS,
                follow_redirects=True,
            ) as client:
                final_url, aweme_id = await resolve_url(clean_url, client=client)
                result = await fetch_work_info(aweme_id, clean_url, final_url, client=client)

                return result.model_dump()

        except Exception as e:
            self._emit_log(f"解析链接失败: {e}")
            return None

    async def _download_file(self, url: str, filepath: Path, timeout: float = 60.0) -> bool:
        """下载文件，上报详细进度"""
        try:
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = 0

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))

                    with open(filepath, "wb") as f:
                        downloaded = 0
                        async for chunk in resp.aiter_bytes(chunk_size=65536):
                            f.write(chunk)
                            downloaded += len(chunk)

                            current_time = time.time()

                            # 每0.5秒更新一次进度
                            if current_time - last_update_time >= 0.5 or (total > 0 and downloaded == total):
                                speed = (downloaded - last_downloaded) / (current_time - last_update_time) if current_time > last_update_time else 0
                                last_update_time = current_time
                                last_downloaded = downloaded

                                downloaded_mb = downloaded / (1024 * 1024)

                                if total > 0:
                                    progress = downloaded / total * 100
                                    total_mb = total / (1024 * 1024)

                                    # 计算速度
                                    if speed > 0:
                                        speed_mb = speed / (1024 * 1024)
                                        remaining = (total - downloaded) / speed
                                        eta_str = self._format_time(remaining)
                                        speed_str = f"{speed_mb:.1f} MB/s"
                                    else:
                                        speed_str = "计算中..."
                                        eta_str = "计算中..."

                                    self._emit_progress({
                                        "percent": progress,
                                        "downloaded_mb": round(downloaded_mb, 2),
                                        "total_mb": round(total_mb, 2),
                                        "speed_str": speed_str,
                                        "eta": eta_str,
                                    })
                                else:
                                    self._emit_progress({
                                        "percent": None,
                                        "downloaded_mb": round(downloaded_mb, 2),
                                        "total_mb": None,
                                        "speed_str": None,
                                        "eta": None,
                                    })

                    if not self.on_event:
                        print()  # CLI 单行刷新结束后换行
            return True
        except Exception as e:
            self._emit_log(f"\n下载失败: {e}")
            return False

    def _format_time(self, seconds: float) -> str:
        """格式化时间"""
        if seconds < 60:
            return f"{seconds:.0f}秒"
        elif seconds < 3600:
            minutes = seconds // 60
            secs = seconds % 60
            return f"{minutes:.0f}分{secs:.0f}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours:.0f}时{minutes:.0f}分"

    def _select_quality_url(self, qualities: list, target_quality: str) -> tuple:
        """选择指定画质的视频URL"""
        if not qualities:
            return None, "未知"

        def parse_quality(quality_str: str) -> int:
            match = re.search(r'(\d+)', quality_str)
            return int(match.group(1)) if match else 0

        # 按画质排序
        sorted_q = sorted(qualities, key=lambda q: parse_quality(q.get("quality_name", "")))

        if target_quality == "highest":
            best = sorted_q[-1]
            return best.get("url"), best.get("quality_name", "未知")

        target = parse_quality(target_quality)

        # 尝试精确匹配
        for q in qualities:
            if str(target) in q.get("quality_name", ""):
                return q.get("url"), q.get("quality_name")

        # 选择最接近但不超过目标的画质
        best = None
        for q in sorted_q:
            if parse_quality(q.get("quality_name", "")) <= target:
                best = q

        if best:
            return best.get("url"), best.get("quality_name")

        # 回退到最低画质
        best = sorted_q[0]
        return best.get("url"), best.get("quality_name")

    async def get_real_direct_url(self, url: str) -> Optional[str]:
        """
        获取视频真正的直链（跟踪重定向）

        Args:
            url: aweme.snssdk.com 等CDN接口URL

        Returns:
            真正的视频直链 或 None
        """
        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=False
            ) as client:
                resp = await client.get(url)

                # 跟踪302重定向
                if resp.status_code in (301, 302, 307, 308):
                    real_url = resp.headers.get("location", "")
                    if real_url:
                        return real_url

                # 如果没有重定向，返回原URL
                return url
        except Exception as e:
            self._emit_log(f"获取直链失败: {e}")
            return None

    async def download(self, url_text: str) -> Optional[Dict[str, Any]]:
        """
        下载抖音视频

        返回: {
            "video_1080p": Path,
            "output_dir": Path,
            "title": str,
            "aweme_id": str,
            "result": dict  # 原始解析结果
        } 或 None
        """
        # 解析链接
        self._emit_log("正在解析抖音链接...")
        result = await self._resolve_douyin_link(url_text)

        if not result or not result.get("ok", True):
            error = result.get("error", {}) if result else {}
            self._emit_log(f"解析失败: {error.get('message', '未知错误')}")
            return None

        title = result.get("title", "无标题")
        aweme_id = result.get("aweme_id", "")
        media = result.get("media", {})

        # 检查是否为图文
        if media.get("type") == "图文":
            self._emit_log("检测到图文内容，本工具仅支持视频解析。")
            return None

        video_url = media.get("url")
        qualities = media.get("qualities", [])

        if not video_url and not qualities:
            self._emit_log("未找到视频资源。")
            return None

        # 创建输出目录
        folder_name = self._sanitize_filename(title)
        output_dir = self.output_dir / folder_name
        output_dir.mkdir(parents=True, exist_ok=True)

        # 选择1080P画质
        url_1080p, quality_1080p = self._select_quality_url(qualities, "1080p")
        if not url_1080p:
            url_1080p = video_url
            quality_1080p = "默认"

        self._emit_log(f"标题: {title}")
        self._emit_log(f"作品ID: {aweme_id}")
        self._emit_log(f"1080P画质: {quality_1080p}")

        # 下载1080P视频
        self._emit_log("正在下载1080P视频...")
        video_1080p_path = output_dir / f"{folder_name}_1080p.mp4"

        if video_1080p_path.exists():
            self._emit_log(f"1080P视频已存在: {video_1080p_path.name}")
        else:
            success = await self._download_file(url_1080p, video_1080p_path)
            if not success:
                self._emit_log("1080P视频下载失败。")
                return None

        # 保存info.txt（详细格式）
        info_path = output_dir / "info.txt"
        with open(info_path, "w", encoding="utf-8") as f:
            author = result.get('author', {})
            media = result.get('media', {})
            music = media.get('music', {})

            f.write(f"标题: {title}\n")
            f.write(f"作者: {author.get('nickname', '未知')}\n")
            f.write(f"作品ID: {aweme_id}\n")
            f.write(f"链接: {result.get('resolved_url', '')}\n")
            f.write(f"类型: {media.get('type', 'video')}\n")
            f.write(f"背景音乐: {music.get('title', '无') if music else '无'}\n")

            # 发布时间
            create_time = result.get('create_time')
            if create_time:
                from datetime import datetime, timezone
                try:
                    dt = datetime.fromtimestamp(create_time, tz=timezone.utc)
                    f.write(f"发布时间: {dt.strftime('%Y-%m-%d %H:%M:%S')}\n")
                except:
                    pass

            # 点赞数
            digg_count = result.get('digg_count')
            if digg_count is not None:
                f.write(f"点赞数: {digg_count}\n")

            # 评论数
            comment_count = result.get('comment_count')
            if comment_count is not None:
                f.write(f"评论数: {comment_count}\n")

            # 描述
            desc = result.get('title', '')
            if desc:
                f.write(f"描述: {desc[:100]}\n")

            # 热门评论
            comments = result.get('comments', [])
            if comments:
                f.write(f"\n热门评论 ({len(comments)} 条):\n")
                for i, comment in enumerate(comments[:10], 1):
                    likes = comment.get('like_count', 0)
                    text = comment.get('text', '')
                    like_str = f" [{likes}赞]" if likes > 0 else ""
                    f.write(f"  {i}. {text}{like_str}\n")

        return {
            "video_1080p": video_1080p_path,
            "output_dir": output_dir,
            "title": title,
            "aweme_id": aweme_id,
            "result": result
        }

    def _parse_quality_num(self, quality_str: str) -> int:
        """解析画质字符串为数字"""
        match = re.search(r'(\d+)', quality_str)
        return int(match.group(1)) if match else 0
