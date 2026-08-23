"""Fetch Douyin work metadata and media info using mobile share page."""

from __future__ import annotations

import json
import re
from typing import Optional

import httpx

from .errors import ErrorCode, ResolverError
from .schemas import Author, ImageItem, Media, MusicInfo, ResolveResult, VideoQuality

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/16.6 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# Pattern for embedded data in mobile share page
ROUTER_DATA_RE = re.compile(
    r"window\._ROUTER_DATA\s*=\s*(\{.*?\})\s*</script>",
    re.DOTALL,
)


def _find_video_item(data: dict) -> Optional[dict]:
    """Find video item in _ROUTER_DATA structure."""
    loader_data = data.get("loaderData") or {}
    for key, value in loader_data.items():
        if isinstance(value, dict) and "videoInfoRes" in value:
            video_info = value.get("videoInfoRes") or {}
            item_list = video_info.get("item_list") or []
            if item_list:
                return item_list[0]
    return None


def _extract_video_url(video_data: dict) -> Optional[str]:
    """Extract the best video URL from video data."""
    video = video_data.get("video") or {}

    # Try play_addr first
    play_addr = video.get("play_addr") or {}
    url_list = play_addr.get("url_list") or []
    if url_list:
        return url_list[0]

    # Try play_addr_h264
    play_addr_h264 = video.get("play_addr_h264") or {}
    url_list = play_addr_h264.get("url_list") or []
    if url_list:
        return url_list[0]

    # Try bit_rate list
    bit_rate = video.get("bit_rate") or []
    if bit_rate:
        best = max(bit_rate, key=lambda x: (x.get("bit_rate") or 0))
        play_addr = best.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if url_list:
            return url_list[0]

    return None


def _remove_watermark(url: str) -> str:
    """Replace playwm (with watermark) URL with play (no watermark)."""
    return url.replace("/playwm/", "/play/")


def _extract_all_qualities(video_data: dict) -> list[VideoQuality]:
    """Extract all available video quality options from video data."""
    video = video_data.get("video") or {}
    qualities = []

    bit_rate_list = video.get("bit_rate") or []
    for item in bit_rate_list:
        if not item:
            continue
        play_addr = item.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if not url_list:
            continue

        gear_name = item.get("gear_name") or ""
        bit_rate_val = item.get("bit_rate") or 0

        url = _remove_watermark(url_list[0])
        qualities.append(VideoQuality(
            quality_name=gear_name or "未知",
            bit_rate=bit_rate_val,
            url=url,
            mime="video/mp4",
        ))

    # If no bit_rate options, generate 720p and 1080p options
    if not qualities:
        play_addr = video.get("play_addr") or {}
        url_list = play_addr.get("url_list") or []
        if url_list:
            original_url = url_list[0]
            url_no_wm = _remove_watermark(original_url)

            available_ratios = ["720p", "1080p"]
            bit_rate_map = {"720p": 2000000, "1080p": 4000000}

            for ratio in available_ratios:
                if 'ratio=' in url_no_wm:
                    quality_url = re.sub(r'ratio=\d+p', f'ratio={ratio}', url_no_wm)
                else:
                    separator = '&' if '?' in url_no_wm else '?'
                    quality_url = f'{url_no_wm}{separator}ratio={ratio}'

                qualities.append(VideoQuality(
                    quality_name=ratio,
                    bit_rate=bit_rate_map.get(ratio, 0),
                    url=quality_url,
                    mime="video/mp4",
                ))

    qualities.sort(key=lambda x: x.bit_rate)

    return qualities


def _extract_cover_url(video_data: dict) -> Optional[str]:
    """Extract cover image URL."""
    video = video_data.get("video") or {}
    cover = video.get("cover") or {}
    url_list = cover.get("url_list") or []
    if url_list:
        return url_list[0]

    origin_cover = video.get("origin_cover") or {}
    url_list = origin_cover.get("url_list") or []
    if url_list:
        return url_list[0]

    return None


def _extract_images(item: dict) -> list[ImageItem]:
    """Extract images/videos from item.images for 图文 posts."""
    images_data = item.get("images") or []
    if not images_data:
        return []

    result = []
    for img in images_data:
        if not img:
            continue

        url_list = img.get("url_list") or []
        if not url_list:
            continue

        url = url_list[0]
        # Determine type: check if it's a video or image
        play_addr = img.get("play_addr") or {}
        play_url_list = play_addr.get("url_list") or []

        if play_url_list:
            # It's a video
            video_url = _remove_watermark(play_url_list[0])
            result.append(ImageItem(type="video", url=video_url, mime="video/mp4"))
        else:
            # It's an image - extract format URLs
            urls = {}
            for u in url_list:
                if '.webp' in u:
                    urls['webp'] = u
                elif '.jpeg' in u or '.jpg' in u:
                    urls['jpeg'] = u

            # Default to first URL
            result.append(ImageItem(type="image", url=url, mime="image/jpeg", urls=urls))

    return result


def _extract_music(item: dict) -> Optional[MusicInfo]:
    """Extract background music info from item.music."""
    music_data = item.get("music") or {}
    if not music_data:
        return None

    title = music_data.get("title") or music_data.get("name")
    author = music_data.get("author") or music_data.get("author_name")
    duration = music_data.get("duration")
    mid = music_data.get("mid")

    # Extract music URL
    play_url = music_data.get("play_url") or {}
    url_list = play_url.get("url_list") or play_url.get("uri") or []

    # Try different URL sources
    music_url = None
    if isinstance(url_list, list) and url_list:
        music_url = url_list[0]
    elif isinstance(url_list, str):
        music_url = url_list

    # Try mid_play_info
    if not music_url:
        mid_play_info = music_data.get("mid_play_info") or {}
        url_list = mid_play_info.get("url_list") or []
        if url_list:
            music_url = url_list[0]

    # Try original_musician (user uploaded music)
    if not music_url:
        original = music_data.get("original_musician") or {}
        url_list = original.get("play_url") or []
        if isinstance(url_list, list) and url_list:
            music_url = url_list[0]

    # Try video.play_addr.uri (common for 图文 posts)
    if not music_url:
        video = item.get("video") or {}
        play_addr = video.get("play_addr") or {}
        uri = play_addr.get("uri") or ""
        if uri and ("music" in uri or ".mp3" in uri or "audio" in uri):
            music_url = uri

    if not music_url and not title and not mid:
        return None

    return MusicInfo(
        title=title,
        author=author,
        url=music_url,
        duration=duration,
        mid=mid,
    )


def _parse_video_item(item: dict, input_url: str, final_url: str) -> ResolveResult:
    """Parse a video item dict into ResolveResult."""
    aweme_id = str(item.get("aweme_id", ""))
    desc = item.get("desc", "")
    author_data = item.get("author", {})

    author = None
    if author_data:
        author = Author(
            nickname=author_data.get("nickname", ""),
            sec_uid=author_data.get("sec_uid"),
        )

    # Detect content type: 图文 if images exist, otherwise video
    images = _extract_images(item)
    music_info = _extract_music(item)
    is_image_post = len(images) > 0

    video_url = _extract_video_url(item)
    if video_url:
        video_url = _remove_watermark(video_url)
    cover_url = _extract_cover_url(item)

    # Extract all quality options
    qualities = _extract_all_qualities(item)

    media = None
    if is_image_post:
        media = Media(
            type="图文",
            downloadable=True,
            url=video_url,
            mime="video/mp4",
            qualities=qualities,
            images=images,
            music=music_info,
        )
    elif video_url:
        media = Media(
            type="video",
            downloadable=True,
            url=video_url,
            mime="video/mp4",
            qualities=qualities,
            music=music_info,
        )
    else:
        media = Media(
            type="video",
            downloadable=False,
            reason_if_unavailable="无法在合规边界内获取视频资源",
            music=music_info,
        )

    # Extract publish time and stats
    create_time = item.get("create_time")
    stats = item.get("statistics") or {}
    digg_count = stats.get("digg_count")
    comment_count = stats.get("comment_count")
    share_count = stats.get("share_count")
    play_count = stats.get("play_count")

    return ResolveResult(
        ok=True,
        platform="douyin",
        input_url=input_url,
        resolved_url=final_url,
        aweme_id=aweme_id,
        title=desc,
        author=author,
        cover_url=cover_url,
        media=media,
        comments=[],
        warnings=[],
        create_time=create_time,
        digg_count=digg_count,
        comment_count=comment_count,
        share_count=share_count,
        play_count=play_count,
    )


async def fetch_work_info(
    aweme_id: str,
    input_url: str,
    final_url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> ResolveResult:
    """Fetch work metadata from Douyin mobile share page.

    Strategy:
    1. Fetch the mobile share page (iesdouyin.com)
    2. Extract _ROUTER_DATA JSON
    3. Parse video info from embedded data

    Args:
        aweme_id: The Douyin work ID.
        input_url: Original input URL.
        final_url: Resolved final URL.
        client: Optional shared httpx client. If None, creates a new one.

    Returns:
        ResolveResult with video metadata.

    Raises:
        ResolverError: If metadata cannot be fetched.
    """
    # Detect if it's a note (图文) or slides from the final URL
    is_note = "/note/" in final_url or "/share/note/" in final_url
    is_slides = "/slides/" in final_url or "/share/slides/" in final_url

    # Try multiple URL patterns
    urls_to_try = []
    if is_note:
        urls_to_try.append(f"https://www.iesdouyin.com/share/note/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/video/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/slides/{aweme_id}/")
    elif is_slides:
        urls_to_try.append(f"https://www.iesdouyin.com/share/slides/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/note/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/video/{aweme_id}/")
    else:
        urls_to_try.append(f"https://www.iesdouyin.com/share/video/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/note/{aweme_id}/")
        urls_to_try.append(f"https://www.iesdouyin.com/share/slides/{aweme_id}/")

    html = None
    last_error = None

    for share_url in urls_to_try:
        async def _fetch_with_client(c: httpx.AsyncClient, url: str = share_url) -> str:
            resp = await c.get(url)
            resp.raise_for_status()
            return resp.text

        try:
            fetched_html = None
            if client:
                fetched_html = await _fetch_with_client(client)
            else:
                async with httpx.AsyncClient(
                    timeout=15.0,
                    headers=BROWSER_HEADERS,
                    follow_redirects=True,
                ) as new_client:
                    fetched_html = await _fetch_with_client(new_client)

            # Check if this HTML has _ROUTER_DATA
            if fetched_html and ROUTER_DATA_RE.search(fetched_html):
                html = fetched_html
                break  # Found valid data, stop trying

        except httpx.TimeoutException:
            last_error = ResolverError(
                code=ErrorCode.RESOLVE_FAILED,
                message="获取作品页面超时",
                detail=f"aweme_id: {aweme_id}",
            )
            continue
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                last_error = ResolverError(
                    code=ErrorCode.RATE_LIMITED,
                    message="请求被限制，稍后再试",
                    detail=f"aweme_id: {aweme_id}",
                )
                continue
            last_error = ResolverError(
                code=ErrorCode.RESOLVE_FAILED,
                message=f"获取作品页面失败: HTTP {e.response.status_code}",
                detail=f"aweme_id: {aweme_id}",
            )
            continue
        except httpx.HTTPError as e:
            last_error = ResolverError(
                code=ErrorCode.RESOLVE_FAILED,
                message=f"获取作品页面失败: {e}",
                detail=f"aweme_id: {aweme_id}",
            )
            continue

    if html is None:
        raise last_error or ResolverError(
            code=ErrorCode.RESOLVE_FAILED,
            message="获取作品页面失败",
            detail=f"aweme_id: {aweme_id}",
        )

    # Extract _ROUTER_DATA
    m = ROUTER_DATA_RE.search(html)
    if not m:
        if len(html) < 1000:
            raise ResolverError(
                code=ErrorCode.UPSTREAM_CHANGED,
                message="页面内容异常，解析规则可能需要更新",
                detail=f"aweme_id: {aweme_id}, html_len: {len(html)}",
            )
        raise ResolverError(
            code=ErrorCode.UPSTREAM_CHANGED,
            message="无法从页面提取视频数据，解析规则可能需要更新",
            detail=f"aweme_id: {aweme_id}",
        )

    try:
        data = json.loads(m.group(1), strict=False)
    except json.JSONDecodeError:
        raise ResolverError(
            code=ErrorCode.UPSTREAM_CHANGED,
            message="页面数据解析失败",
            detail=f"aweme_id: {aweme_id}",
        )

    item = _find_video_item(data)
    if not item:
        raise ResolverError(
            code=ErrorCode.AWEME_ID_NOT_FOUND,
            message="页面中未找到视频信息",
            detail=f"aweme_id: {aweme_id}",
        )

    return _parse_video_item(item, input_url, final_url)
