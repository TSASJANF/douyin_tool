"""Error codes and error types for Douyin Link Resolver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ErrorCode(str, Enum):
    """Structured error codes for Agent-friendly error handling."""

    INVALID_INPUT = "INVALID_INPUT"
    UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
    RESOLVE_FAILED = "RESOLVE_FAILED"
    AWEME_ID_NOT_FOUND = "AWEME_ID_NOT_FOUND"
    MEDIA_UNAVAILABLE = "MEDIA_UNAVAILABLE"
    COMMENTS_UNAVAILABLE = "COMMENTS_UNAVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    UPSTREAM_CHANGED = "UPSTREAM_CHANGED"
    LEGAL_RESTRICTED = "LEGAL_RESTRICTED"


# Exit codes for CLI (Agent-friendly)
EXIT_SUCCESS = 0
EXIT_INPUT_ERROR = 2
EXIT_PLATFORM_ERROR = 3
EXIT_RATE_LIMITED = 4
EXIT_UPSTREAM_ERROR = 5


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.INVALID_INPUT: "请粘贴有效的抖音分享链接",
    ErrorCode.UNSUPPORTED_PLATFORM: "当前只支持抖音",
    ErrorCode.RESOLVE_FAILED: "无法解析该分享链接",
    ErrorCode.AWEME_ID_NOT_FOUND: "链接可能失效或不是作品链接",
    ErrorCode.MEDIA_UNAVAILABLE: "当前无法在合规边界内获取视频",
    ErrorCode.COMMENTS_UNAVAILABLE: "评论可能被限制、关闭或需要登录",
    ErrorCode.RATE_LIMITED: "请稍后再试",
    ErrorCode.UPSTREAM_CHANGED: "解析规则需要更新",
    ErrorCode.LEGAL_RESTRICTED: "该内容不适合下载或处理",
}


@dataclass
class ResolverError(Exception):
    """Base error for resolver operations."""

    code: ErrorCode
    message: str
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        super().__init__(self.message)

    @property
    def user_message(self) -> str:
        return ERROR_MESSAGES.get(self.code, self.message)

    def to_dict(self) -> dict:
        return {
            "code": self.code.value,
            "message": self.user_message,
            "detail": self.detail,
        }
