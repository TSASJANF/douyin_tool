"""Parse user input text and extract Douyin URLs."""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from .errors import ErrorCode, ResolverError

# Patterns for Douyin URLs
DOUYIN_SHORT_LINK_RE = re.compile(
    r"https?://v\.douyin\.com/[A-Za-z0-9]+/?",
)
DOUYIN_LONG_LINK_RE = re.compile(
    r"https?://www\.douyin\.com/video/(\d+)",
)
DOUYIN_DISCOVER_RE = re.compile(
    r"https?://www\.douyin\.com/discover\?modal_id=(\d+)",
)
DOUYIN_NOTE_RE = re.compile(
    r"https?://www\.douyin\.com/note/(\d+)",
)
DOUYIN_SHARE_VIDEO_RE = re.compile(
    r"https?://www\.iesdouyin\.com/share/video/(\d+)",
)
DOUYIN_SHARE_NOTE_RE = re.compile(
    r"https?://www\.iesdouyin\.com/share/note/(\d+)",
)
DOUYIN_SHARE_SLIDES_RE = re.compile(
    r"https?://www\.iesdouyin\.com/share/slides/(\d+)",
)

DOUYIN_DOMAINS = {"v.douyin.com", "www.douyin.com", "douyin.com", "www.iesdouyin.com", "iesdouyin.com"}


def extract_urls(text: str) -> list:
    """Extract all URLs from arbitrary text input."""
    url_pattern = re.compile(r"https?://[^\s<>\"']+")
    return url_pattern.findall(text)


def is_douyin_url(url: str) -> bool:
    """Check if a URL is a Douyin link."""
    try:
        parsed = urlparse(url)
        return parsed.hostname in DOUYIN_DOMAINS
    except Exception:
        return False


def extract_aweme_id_from_url(url: str) -> Optional[str]:
    """Try to extract aweme_id directly from the URL without network requests."""
    m = DOUYIN_LONG_LINK_RE.search(url)
    if m:
        return m.group(1)

    m = DOUYIN_DISCOVER_RE.search(url)
    if m:
        return m.group(1)

    m = DOUYIN_NOTE_RE.search(url)
    if m:
        return m.group(1)

    m = DOUYIN_SHARE_VIDEO_RE.search(url)
    if m:
        return m.group(1)

    m = DOUYIN_SHARE_NOTE_RE.search(url)
    if m:
        return m.group(1)

    m = DOUYIN_SHARE_SLIDES_RE.search(url)
    if m:
        return m.group(1)

    return None


def parse_input(text: str) -> str:
    """Parse user input and return a validated Douyin URL.

    Handles:
    - Raw URLs
    - Text containing URLs (e.g. share messages)
    - Douyin share text with 口令

    Returns the first valid Douyin URL found.
    Raises ResolverError if no valid URL is found.
    """
    text = text.strip()
    if not text:
        raise ResolverError(
            code=ErrorCode.INVALID_INPUT,
            message="输入为空",
        )

    if text.startswith("http"):
        url = text.split()[0]
        if is_douyin_url(url):
            return url
        raise ResolverError(
            code=ErrorCode.UNSUPPORTED_PLATFORM,
            message=f"非抖音链接: {url}",
        )

    urls = extract_urls(text)
    douyin_urls = [u for u in urls if is_douyin_url(u)]

    if douyin_urls:
        return douyin_urls[0]

    if urls:
        raise ResolverError(
            code=ErrorCode.UNSUPPORTED_PLATFORM,
            message=f"找到链接但不是抖音: {urls[0]}",
        )

    raise ResolverError(
        code=ErrorCode.INVALID_INPUT,
        message="未找到有效链接",
    )
