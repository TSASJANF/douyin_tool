"""下载器公共能力：输出目录、日志/进度事件、带重试的文件下载。

抖音与视频号下载器只在「怎么解析链接、下载哪一个直链」上不同，落盘这一层完全一致，
因此抽到这里复用。

支持事件回调：构造时传入 on_event(type, data) 可将日志与下载进度转发给外部（如 WebUI）；
不传时保持原有 print 输出，CLI 行为不变。
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

EventCallback = Callable[[str, dict], None]

# 视为瞬时故障、值得重试的 HTTP 状态码（限流/服务端错误）
RETRYABLE_HTTP_STATUS = {429, 500, 502, 503, 504}
# 重试退避：第 n 次重试前等待 n * RETRY_DELAY_BASE 秒
RETRY_DELAY_BASE = 2.0


class _DownloadError(Exception):
    """单次下载失败；retryable 标记该错误是否值得重试"""

    def __init__(self, message: str, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


def sanitize_filename(name: str) -> str:
    """清理文件名，移除非法字符"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\n\r]', '', name)
    name = name.strip(' .')
    if len(name) > 80:
        name = name[:80]
    return name.strip() or "untitled"


class BaseDownloader:
    """下载器基类：负责落盘、进度与重试；子类实现 download()/prepare_analysis_url()"""

    platform = ""

    def __init__(self, download_config: dict, on_event: Optional[EventCallback] = None):
        self.config = download_config or {}
        self.on_event = on_event
        self.output_dir = Path(__file__).parent.parent / self.config.get("download_dir", "output")
        self.max_retry = self.config.get("max_retry", 3)
        # 最近一次 download 失败的具体原因，供上层（pipeline）透出给用户
        self.last_error: Optional[str] = None

        # 确保输出目录存在
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ---------------- 事件输出 ----------------

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

    # ---------------- 下载 ----------------

    async def _download_file(self, url: str, filepath: Path, timeout: float = 60.0,
                             headers: Optional[dict] = None) -> bool:
        """下载文件（带重试），上报详细进度。

        瞬时网络故障（DNS/连接/超时）与 429/5xx 自动重试，间隔递增；
        失败原因写入 self.last_error 供上层透出。
        """
        attempts = 1 + max(0, self.max_retry)

        for attempt in range(1, attempts + 1):
            try:
                await self._download_once(url, filepath, timeout, headers=headers)
                return True
            except _DownloadError as e:
                if not e.retryable or attempt >= attempts:
                    self.last_error = f"视频下载失败: {e}"
                    self._emit_log(f"\n{self.last_error}")
                    return False
                delay = attempt * RETRY_DELAY_BASE
                self._emit_log(
                    f"\n下载失败（第 {attempt}/{attempts} 次尝试）: {e}，{delay:.0f} 秒后重试"
                )
                await asyncio.sleep(delay)

        return False

    async def _download_once(self, url: str, filepath: Path, timeout: float,
                             headers: Optional[dict] = None) -> None:
        """单次下载尝试：成功写入 filepath，失败抛 _DownloadError。

        先写 .part 临时文件，成功后原子改名，失败不残留半截文件
        （半截文件会被 download() 的"已存在则跳过"误判为已下载完成）。
        """
        tmp_path = filepath.parent / (filepath.name + ".part")
        try:
            start_time = time.time()
            last_update_time = start_time
            last_downloaded = 0

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True,
                                         headers=headers or None) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))

                    with open(tmp_path, "wb") as f:
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
            tmp_path.replace(filepath)
        except httpx.HTTPStatusError as e:
            code = e.response.status_code
            raise _DownloadError(f"HTTP {code}", retryable=code in RETRYABLE_HTTP_STATUS)
        except httpx.TransportError as e:
            # DNS 解析失败、连接失败、读写超时等瞬时网络故障
            raise _DownloadError(f"{type(e).__name__}: {e}", retryable=True)
        except Exception as e:
            raise _DownloadError(f"{type(e).__name__}: {e}")
        finally:
            tmp_path.unlink(missing_ok=True)

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

    # ---------------- 子类接口 ----------------

    async def download(self, url_text: str):
        """解析链接并下载，返回结果字典；失败返回 None（原因见 self.last_error）"""
        raise NotImplementedError

    async def prepare_analysis_url(self, download_result: dict):
        """从下载结果里取出送 MiMo 解析的直链；失败返回 None（原因见 self.last_error）"""
        raise NotImplementedError
