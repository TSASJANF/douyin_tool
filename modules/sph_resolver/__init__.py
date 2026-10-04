"""视频号（微信视频号 / sph）链接解析包（自包含）。

解析流程移植自开源项目 wx_channels_download（ltaoo），详见 resolver.py 顶部说明。
"""

from .errors import ErrorCode, SphResolverError
from .input_parser import extract_sph_id, is_sph_url, normalize_share_url
from .resolver import SphResolver, SphVideoInfo, pick_video_url

__all__ = [
    "ErrorCode",
    "SphResolverError",
    "SphResolver",
    "SphVideoInfo",
    "is_sph_url",
    "extract_sph_id",
    "normalize_share_url",
    "pick_video_url",
]
