"""Resolve Douyin short links to final URLs and extract aweme_id."""

from __future__ import annotations

import re
from typing import Optional, Tuple

import httpx

from .errors import ErrorCode, ResolverError

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

AWEME_ID_RE = re.compile(r"/(?:share/)?video/(\d+)")
MODAL_ID_RE = re.compile(r"modal_id=(\d+)")
NOTE_ID_RE = re.compile(r"/(?:share/)?note/(\d+)")
SLIDES_ID_RE = re.compile(r"/(?:share/)?slides/(\d+)")


async def resolve_short_link(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Follow redirects on a Douyin short link and return the final URL."""

    async def _resolve_with_client(c: httpx.AsyncClient) -> str:
        # Always use follow_redirects=False to manually track redirects
        # This overrides the client's default setting
        resp = await c.get(url, follow_redirects=False)

        max_redirects = 15  # Increased from 10
        current_url = url
        redirect_count = 0

        for _ in range(max_redirects):
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location", "")
                if not location:
                    break
                if location.startswith("/"):
                    from urllib.parse import urljoin
                    location = urljoin(current_url, location)
                current_url = location
                redirect_count += 1
                resp = await c.get(current_url, follow_redirects=False)
            else:
                break

        # Check if we got a valid response
        if resp.status_code >= 400:
            raise ResolverError(
                code=ErrorCode.RESOLVE_FAILED,
                message=f"短链返回错误状态码: {resp.status_code}",
                detail=f"URL: {url}, Final URL: {current_url}",
            )

        return current_url

    try:
        if client:
            return await _resolve_with_client(client)
        else:
            async with httpx.AsyncClient(
                follow_redirects=False,
                timeout=20.0,  # Increased timeout
                headers=BROWSER_HEADERS,
            ) as new_client:
                return await _resolve_with_client(new_client)

    except httpx.TimeoutException:
        raise ResolverError(
            code=ErrorCode.RESOLVE_FAILED,
            message="短链请求超时",
            detail=f"URL: {url} (timeout: 20s)",
        )
    except httpx.HTTPError as e:
        raise ResolverError(
            code=ErrorCode.RESOLVE_FAILED,
            message=f"短链请求失败: {type(e).__name__}",
            detail=f"URL: {url}, Error: {str(e)}",
        )


def extract_aweme_id(final_url: str) -> str:
    """Extract aweme_id from a resolved Douyin URL."""
    m = AWEME_ID_RE.search(final_url)
    if m:
        return m.group(1)

    m = MODAL_ID_RE.search(final_url)
    if m:
        return m.group(1)

    m = NOTE_ID_RE.search(final_url)
    if m:
        return m.group(1)

    m = SLIDES_ID_RE.search(final_url)
    if m:
        return m.group(1)

    raise ResolverError(
        code=ErrorCode.AWEME_ID_NOT_FOUND,
        message=f"无法从 URL 提取作品 ID: {final_url}",
    )


async def resolve_url(
    url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[str, str]:
    """Resolve a Douyin URL to get the final URL and aweme_id.

    Args:
        url: Douyin URL to resolve.
        client: Optional shared httpx client.

    Returns:
        Tuple of (final_url, aweme_id).
    """
    from .input_parser import extract_aweme_id_from_url, is_douyin_url

    if not is_douyin_url(url):
        raise ResolverError(
            code=ErrorCode.UNSUPPORTED_PLATFORM,
            message=f"非抖音链接: {url}",
        )

    direct_id = extract_aweme_id_from_url(url)
    if direct_id:
        return url, direct_id

    try:
        final_url = await resolve_short_link(url, client=client)
    except ResolverError:
        raise
    except Exception as e:
        raise ResolverError(
            code=ErrorCode.RESOLVE_FAILED,
            message=f"短链解析异常: {type(e).__name__}",
            detail=f"URL: {url}, Error: {str(e)}",
        )

    try:
        aweme_id = extract_aweme_id(final_url)
    except ResolverError:
        raise ResolverError(
            code=ErrorCode.AWEME_ID_NOT_FOUND,
            message=f"无法从解析后的URL提取作品ID",
            detail=f"原始URL: {url}, 解析后URL: {final_url}",
        )

    return final_url, aweme_id
