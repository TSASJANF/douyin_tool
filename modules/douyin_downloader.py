"""
抖音视频下载模块
提取自原抖音下载部分的逻辑

落盘/进度/重试等公共能力在 BaseDownloader（modules/base_downloader.py），
本模块只保留抖音特有的链接解析、画质选择与直链跟踪。

支持事件回调：构造时传入 on_event(type, data) 可将日志与下载进度转发给
外部（如 WebUI）；不传时保持原有 print 输出，CLI 行为不变。
"""

import re
from typing import Optional, Dict, Any

import httpx

from .base_downloader import BaseDownloader, EventCallback, sanitize_filename
from .douyin_resolver import parse_input, resolve_url, fetch_work_info, BROWSER_HEADERS

# 兼容旧引用（server/api/uploads.py 从这里导入 sanitize_filename）
__all__ = ["DouyinDownloader", "sanitize_filename"]


class DouyinDownloader(BaseDownloader):
    """抖音视频下载器"""

    platform = "douyin"

    def __init__(self, config: dict, on_event: Optional[EventCallback] = None):
        super().__init__(config, on_event=on_event)
        self.video_quality = self.config.get("video_quality", "highest")

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
            self.last_error = f"解析链接失败: {e}"
            self._emit_log(self.last_error)
            return None

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
            msg = f"获取直链失败: {e}"
            self.last_error = msg
            self._emit_log(msg)
            return None

    async def prepare_analysis_url(self, download_result: dict) -> Optional[str]:
        """从下载结果里挑 720P 直链并跟踪 302，得到可送 MiMo 解析的真正直链。

        失败原因写入 self.last_error 供 pipeline 透出。
        """
        self.last_error = None

        result = (download_result or {}).get("result", {})
        qualities = result.get("media", {}).get("qualities", [])

        url_720p = None
        for q in qualities:
            if "720" in q.get("quality_name", ""):
                url_720p = q.get("url")
                break

        if not url_720p:
            self.last_error = ("未找到 720P 清晰度的视频直链：该作品可能没有此清晰度，"
                               "或链接已失效，请重试或换一个视频")
            return None

        self._emit_log(f"720P接口URL: {url_720p[:80]}...")

        real_direct_url = await self.get_real_direct_url(url_720p)
        if not real_direct_url:
            self.last_error = self.last_error or (
                "获取真正直链失败：CDN 接口未返回 302 跳转地址，直链可能已失效，请重试")
            return None

        self._emit_log(f"720P真正直链: {real_direct_url[:80]}...")
        return real_direct_url

    async def download(self, url_text: str) -> Optional[Dict[str, Any]]:
        """
        下载抖音视频

        返回: {
            "video_1080p": Path,
            "output_dir": Path,
            "title": str,
            "aweme_id": str,
            "platform": "douyin",
            "result": dict  # 原始解析结果
        } 或 None
        """
        self.last_error = None

        # 解析链接
        self._emit_log("正在解析抖音链接...")
        result = await self._resolve_douyin_link(url_text)

        if not result or not result.get("ok", True):
            error = result.get("error", {}) if result else {}
            self.last_error = f"解析失败: {error.get('message', '未知错误')}"
            self._emit_log(self.last_error)
            return None

        title = result.get("title", "无标题")
        aweme_id = result.get("aweme_id", "")
        media = result.get("media", {})

        # 检查是否为图文
        if media.get("type") == "图文":
            self.last_error = "该链接为图文内容，本工具仅支持视频。"
            self._emit_log(self.last_error)
            return None

        video_url = media.get("url")
        qualities = media.get("qualities", [])

        if not video_url and not qualities:
            self.last_error = "未找到视频资源。"
            self._emit_log(self.last_error)
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
            # 失败原因已记入 last_error 并输出日志
            if not await self._download_file(url_1080p, video_1080p_path):
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
            "platform": self.platform,
            "result": result
        }

    def _parse_quality_num(self, quality_str: str) -> int:
        """解析画质字符串为数字"""
        match = re.search(r'(\d+)', quality_str)
        return int(match.group(1)) if match else 0
