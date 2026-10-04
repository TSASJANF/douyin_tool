"""视频号解析的错误类型（与 douyin_resolver.errors 保持同样的用法）。"""


class ErrorCode:
    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_PLATFORM = "unsupported_platform"
    MISSING_COOKIE = "missing_cookie"
    COOKIE_INVALID = "cookie_invalid"
    PARSE_FAILED = "parse_failed"
    CONTENT_UNAVAILABLE = "content_unavailable"
    NO_VIDEO = "no_video"
    NETWORK = "network"


class SphResolverError(Exception):
    """视频号解析失败；message 面向用户，直接可展示"""

    def __init__(self, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}

    def __str__(self) -> str:
        return self.message
