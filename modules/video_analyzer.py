"""
视频解析模块
使用MiMo API分析视频内容，提取文案

支持事件回调：构造时传入 on_event(type, data) 可将日志转发给外部（如 WebUI）；
不传时保持原有 print 输出，CLI 行为不变。
"""

import os
import sys
import base64
import mimetypes
from pathlib import Path
from typing import Optional, Callable

from openai import OpenAI

EventCallback = Callable[[str, dict], None]


class VideoAnalyzer:
    """视频解析器"""

    def __init__(self, mimo_config: dict, analysis_config: dict,
                 on_event: Optional[EventCallback] = None):
        self.api_key = mimo_config.get("api_key")
        self.base_url = mimo_config.get("base_url", "https://api.xiaomimimo.com/v1")
        self.model = mimo_config.get("model", "mimo-v2.5")
        self.max_tokens = mimo_config.get("max_completion_tokens", 131072)

        self.fps = analysis_config.get("fps", 6)
        self.media_resolution = analysis_config.get("media_resolution", "default")
        self.prompt = analysis_config.get("prompt", "一字不差地提取完整文案")

        self.on_event = on_event
        self.client = None
        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=1800.0,
                max_retries=0
            )

    def _emit_log(self, text: str):
        """输出日志：有回调时发事件，否则打印"""
        if self.on_event:
            self.on_event("log", {"text": text})
        else:
            print(text)

    def _get_mime_type(self, file_path: str) -> str:
        """获取文件MIME类型"""
        mime_type, _ = mimetypes.guess_type(file_path)
        if mime_type:
            return mime_type

        ext = Path(file_path).suffix.lower()
        mime_map = {
            ".mp4": "video/mp4",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
            ".mov": "video/quicktime",
            ".wmv": "video/x-ms-wmv"
        }
        return mime_map.get(ext, "video/mp4")

    def _file_to_base64(self, file_path: str) -> str:
        """将文件转换为Base64编码"""
        with open(file_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("utf-8")

    def analyze_local_video(self, video_path: str) -> Optional[str]:
        """
        分析本地视频文件

        返回: 提取的文案内容 或 None
        """
        if not self.client:
            self._emit_log("错误: MiMo API未配置")
            return None

        if not os.path.exists(video_path):
            self._emit_log(f"错误: 视频文件不存在: {video_path}")
            return None

        file_size = os.path.getsize(video_path)
        self._emit_log(f"视频文件大小: {file_size / (1024*1024):.2f} MB")

        try:
            # 转换为Base64
            self._emit_log("正在编码视频文件...")
            base64_data = self._file_to_base64(video_path)
            mime_type = self._get_mime_type(video_path)
            video_url = f"data:{mime_type};base64,{base64_data}"

            self._emit_log("正在调用MiMo API分析视频...")
            self._emit_log(f"FPS: {self.fps}, 分辨率: {self.media_resolution}")

            # 调用API（新版客户端用 max_completion_tokens，旧版回退 max_tokens）
            request_kwargs = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are MiMo, an AI assistant developed by Xiaomi."},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": video_url},
                                "fps": self.fps,
                                "media_resolution": self.media_resolution
                            },
                            {"type": "text", "text": self.prompt}
                        ]
                    }
                ],
                "max_completion_tokens": self.max_tokens,
                "stream": False
            }
            try:
                response = self.client.chat.completions.create(**request_kwargs)
            except TypeError:
                # 旧版 openai 客户端不支持 max_completion_tokens，回退 max_tokens
                # （MiMo 对 max_tokens 上限为 131072，超出会被拒绝）
                capped = min(self.max_tokens, 131072)
                if capped != self.max_tokens:
                    self._emit_log(f"max_tokens 已按模型上限调整为 {capped}")
                request_kwargs.pop("max_completion_tokens", None)
                request_kwargs["max_tokens"] = capped
                response = self.client.chat.completions.create(**request_kwargs)

            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                self._emit_log("视频分析完成！")
                return content
            else:
                self._emit_log("API返回空结果")
                return None

        except Exception as e:
            self._emit_log(f"视频分析失败: {e}")
            return None

    def analyze_remote_video(self, video_url: str) -> Optional[str]:
        """
        分析远程视频链接

        返回: 提取的文案内容 或 None
        """
        if not self.client:
            self._emit_log("错误: MiMo API未配置")
            return None

        try:
            self._emit_log("正在调用MiMo API分析远程视频...")
            self._emit_log(f"FPS: {self.fps}, 分辨率: {self.media_resolution}")

            # 调用API
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "你是一个视频分析专家，特点是不会遗漏视频的任何一个细节。"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "video_url",
                                "video_url": {"url": video_url},
                                "fps": self.fps,
                                "media_resolution": self.media_resolution
                            },
                            {"type": "text", "text": self.prompt}
                        ]
                    }
                ],
                stream=False
            )

            if response.choices and len(response.choices) > 0:
                content = response.choices[0].message.content
                self._emit_log("视频分析完成！")
                return content
            else:
                self._emit_log("API返回空结果")
                return None

        except Exception as e:
            self._emit_log(f"视频分析失败: {e}")
            return None
