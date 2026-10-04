"""识别并规范化视频号（sph）分享链接。"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from ..douyin_resolver.input_parser import extract_urls

# 视频号分享短链：https://weixin.qq.com/sph/A9i6FjGbC0
SPH_SHORT_LINK_RE = re.compile(r"https?://weixin\.qq\.com/sph/([A-Za-z0-9_-]+)")
# 短链在浏览器里打开后的地址：https://channels.weixin.qq.com/finder-preview/pages/sph?id=xxxx
SPH_PREVIEW_RE = re.compile(
    r"https?://channels\.weixin\.qq\.com/finder-preview/pages/sph\?(?:[^\s#]*&)?id=([A-Za-z0-9_-]+)"
)

SPH_DOMAINS = {"weixin.qq.com", "channels.weixin.qq.com"}

# 规范化后的分享短链前缀（腾讯元宝解析接口只认这种形态）
_CANONICAL_PREFIX = "https://weixin.qq.com/sph/"


def is_sph_url(url: str) -> bool:
    """判断是否为视频号分享链接（短链或其网页版地址）"""
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False
    if host not in SPH_DOMAINS:
        return False
    return bool(SPH_SHORT_LINK_RE.search(url) or SPH_PREVIEW_RE.search(url))


def extract_sph_id(url: str) -> Optional[str]:
    """从分享链接里取出视频号内容 id（短链或网页版地址都支持）"""
    for pattern in (SPH_SHORT_LINK_RE, SPH_PREVIEW_RE):
        m = pattern.search(url)
        if m:
            return m.group(1)
    return None


def normalize_share_url(text: str) -> str:
    """从任意文本里提取视频号分享链接，并统一成元宝接口认识的短链形态。

    网页版地址（.../finder-preview/pages/sph?id=xxx）会被还原为
    https://weixin.qq.com/sph/xxx —— 两种形态都来自同一次分享，内容 id 相同。
    找不到视频号链接时返回空串。
    """
    text = (text or "").strip()
    if not text:
        return ""

    candidates = []
    if is_sph_url(text):
        candidates.append(text)
    candidates.extend(u for u in extract_urls(text) if is_sph_url(u))

    for url in candidates:
        sph_id = extract_sph_id(url)
        if sph_id:
            return f"{_CANONICAL_PREFIX}{sph_id}"
    return ""
