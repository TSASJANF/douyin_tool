"""抖音链接解析包（自包含版本，内置自原"抖音视频下载部分"项目 packages/core）。"""

from .errors import ErrorCode, ResolverError
from .schemas import ResolveResult
from .input_parser import parse_input
from .url_resolver import resolve_url, BROWSER_HEADERS
from .douyin_provider import fetch_work_info

__all__ = [
    "ErrorCode",
    "ResolverError",
    "ResolveResult",
    "parse_input",
    "resolve_url",
    "fetch_work_info",
    "BROWSER_HEADERS",
]
