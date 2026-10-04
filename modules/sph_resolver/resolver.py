"""视频号分享链接解析。

流程移植自知名开源项目 wx_channels_download（ltaoo，Go，MIT + Commons Clause），
对应其 `pkg/scraper/wxchannels/yuanbao.go` 与 `internal/workers/sph/worker.js`：
不是自己发明的算法，而是复用该项目已验证的两步接口调用。

  1. POST https://yuanbao.tencent.com/api/weixin/get_parse_result
       {"type": "video_channel_url", "url": <分享短链>, "scene": 1}
       需要 yuanbao.tencent.com 的登录 Cookie，返回 wx_export_id 与 playable_url
  2. 从 playable_url 的 query 取出 token(generalToken) / eid(exportId)
  3. POST https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info
       {"baseReq": {"generalToken": ...}, "exportId": ...}
       返回 data.feedInfo.h264VideoInfo.videoUrl 等 → 可下载直链

视频号没有公开 API，第 1 步的登录态无法绕过（无 Cookie 时接口直接返回 401），
因此提供两条路，二选一即可：

  - 内置流程（默认）：在 sph.cookie 填腾讯元宝登录 Cookie（或设环境变量 SPH_COOKIE）；
  - 外部流程（推荐给已装 wx_channels_download 的用户）：在 sph.api_base 填本机
    运行的 wx_channels_download 服务地址，由它负责解析（它能自动读取本机 Cookie），
    本工具只消费结果 —— 即直接复用该项目，不重造解析逻辑。
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional
from urllib.parse import parse_qs, quote, urlencode, urlparse

import httpx

from .errors import ErrorCode, SphResolverError
from .input_parser import extract_sph_id, normalize_share_url

EventCallback = Callable[[str, dict], None]

YUANBAO_PARSE_URL = "https://yuanbao.tencent.com/api/weixin/get_parse_result"
FEED_INFO_URL = "https://channels.weixin.qq.com/finder-preview/api/feed/get_feed_info"

USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

MEDIA_TYPE_PICTURE = 2
MEDIA_TYPE_VIDEO = 4

# 元宝接口要求的一批浏览器指纹头；沿用 wx_channels_download 里验证可用的固定值（非机密）
_YUANBAO_EXTRA_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8",
    "origin": "https://yuanbao.tencent.com",
    "referer": "https://yuanbao.tencent.com/chat/naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "user-agent": USER_AGENT,
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
    "t-userid": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-agentid": "naQivTmsDa/cf4d0079-ed1b-4c55-a3f3-2ca1379727d1",
    "x-commit-tag": "72282a0d",
    "x-device-id": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-hy106": "",
    "x-hy92": "e963067ffa31002b9646bd0c03000008b1951a",
    "x-hy93": "1921b001708100d7fa31002b9646bd0cc15a3e2e1f",
    "x-id": "b9575f6b0a8c4a55a08096904a5ef20a",
    "x-instance-id": "5",
    "x-language": "zh-CN",
    "x-os_version": "Mac OS(10.15.7)-Blink",
    "x-platform": "mac",
    "x-requested-with": "XMLHttpRequest",
    "x-source": "web",
    "x-web-third-source": "main",
    "x-webdriver": "0",
    "x-webversion": "2.69.0",
    "x-ybuitest": "0",
}

_FEED_INFO_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://channels.weixin.qq.com",
    # 接口会校验 Referer：缺失时直接 401 "permission verification failed"。
    # 解析 exportId 时会被改写为带 token/eid 的 feed 页地址。
    "Referer": "https://channels.weixin.qq.com/finder-preview/pages/feed",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": USER_AGENT,
    "sec-ch-ua": '"Chromium";v="148", "Google Chrome";v="148", "Not/A)Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

_COOKIE_WHY = (
    "视频号没有公开 API，本工具用的是 wx_channels_download 的分享链接解析流程"
    "（元宝解析接口 → 视频号 feed 接口），其中第一步必须有腾讯元宝"
    "（yuanbao.tencent.com）的登录 Cookie。"
)
_COOKIE_HOW = (
    "填法：浏览器登录 https://yuanbao.tencent.com 后，在开发者工具 Network 里复制请求的完整 "
    "Cookie 值，粘贴到「设置 → 视频号」的 sph.cookie（或设置环境变量 SPH_COOKIE）。"
    "已安装 wx_channels_download 的用户，也可以改为在 sph.api_base 填入其服务地址，由它来解析。"
)
MISSING_COOKIE_HINT = _COOKIE_WHY + _COOKIE_HOW


@dataclass
class SphVideoInfo:
    """一次视频号解析的结果"""

    title: str
    author: str = ""
    description: str = ""
    video_url: str = ""
    cover_url: str = ""
    create_time: int = 0
    media_type: int = MEDIA_TYPE_VIDEO
    export_id: str = ""
    share_url: str = ""
    stats: Dict[str, str] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)


def _generate_rid() -> str:
    """feed 接口的 _rid 参数：时间戳十六进制 + 8 位随机十六进制"""
    stamp = f"{int(time.time()):x}"
    rand = "".join(random.choice("0123456789abcdef") for _ in range(8))
    return f"{stamp}-{rand}"


def pick_video_url(feed_info: dict) -> str:
    """按 wx_channels_download 的顺序取直链：h264 → videoUrl → h265（h264 兼容性最好）"""
    for path in (("h264VideoInfo", "videoUrl"), ("videoUrl",), ("h265VideoInfo", "videoUrl")):
        node: Any = feed_info
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if isinstance(node, str) and node.strip():
            return node.strip()
    return ""


def _find_feed(payload: Any) -> Optional[dict]:
    """在响应里定位 data 层（含 feedInfo / authorInfo / errMsg 的那一层）。

    兼容外部服务再包一层 data 的情况。判定方式：
      - 出现 feedInfo → 就是这一层；
      - errMsg 是对象（dict）而不是字符串 → 这一层是 data 层
        （顶层 errMsg 是字符串，内容不可播放时 data 层只有 errMsg 没有 feedInfo）。
    """
    node = payload
    for _ in range(4):
        if not isinstance(node, dict):
            return None
        if "feedInfo" in node:
            return node
        if isinstance(node.get("errMsg"), dict):
            return node
        node = node.get("data")
    return None


def _plain_text(value: Any) -> str:
    """去掉 errMsg 里可能带的 HTML 标签，压成一行"""
    text = str(value or "")
    out, inside = [], False
    for ch in text:
        if ch == "<":
            inside = True
        elif ch == ">":
            inside = False
        elif not inside:
            out.append(ch)
    return " ".join("".join(out).split())


class SphResolver:
    """解析视频号分享链接，产出可下载直链与元信息"""

    def __init__(self, config: Optional[dict] = None, on_event: Optional[EventCallback] = None):
        config = config or {}
        self.cookie = (config.get("cookie") or "").strip() or os.environ.get("SPH_COOKIE", "").strip()
        self.api_base = (config.get("api_base") or "").strip().rstrip("/")
        self.api_token = ((config.get("api_token") or "").strip()
                          or os.environ.get("SPH_API_TOKEN", "").strip())
        self.on_event = on_event
        self.last_error: Optional[str] = None

    # ---------------- 基础输出 ----------------

    def _emit_log(self, text: str):
        if self.on_event:
            self.on_event("log", {"text": text})
        else:
            print(text)

    # ---------------- 对外入口 ----------------

    async def resolve(self, text: str) -> SphVideoInfo:
        """解析分享链接（或含链接的分享文本），失败抛 SphResolverError"""
        share_url = normalize_share_url(text)
        if not share_url:
            raise SphResolverError(
                ErrorCode.INVALID_INPUT,
                "未找到视频号分享链接（形如 https://weixin.qq.com/sph/xxxxxx）",
            )

        if self.api_base:
            self._emit_log(f"使用外部视频号解析服务: {self.api_base}")
            feed = await self._fetch_via_external(share_url)
        else:
            feed = await self._fetch_via_yuanbao(share_url)

        return self._build_info(feed, share_url)

    async def probe_metadata(self, text: str) -> Optional[SphVideoInfo]:
        """免登录探测分享链接的元信息（标题/作者/封面）。

        分享链接的网页版接口在未登录时也会返回这些字段，用于在缺少 Cookie 时
        告诉用户"链接本身是好的，只是缺登录态"，而不是一句笼统的失败。
        探测失败一律返回 None，不影响主流程报错。
        """
        share_url = normalize_share_url(text)
        sph_id = extract_sph_id(share_url) if share_url else None
        if not sph_id:
            return None
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                headers = dict(_FEED_INFO_HEADERS)
                headers["Referer"] = (
                    f"https://channels.weixin.qq.com/finder-preview/pages/sph?id={sph_id}"
                )
                resp = await self._post_json(
                    client, FEED_INFO_URL,
                    {"baseReq": {"generalToken": ""}, "shortUri": sph_id},
                    headers=headers, what="视频号分享页接口",
                    raise_on_auth=False,
                )
            return self._build_info(resp, share_url, require_video=False)
        except Exception:
            return None

    # ---------------- 内置流程（元宝 → 视频号 feed） ----------------

    async def _fetch_via_yuanbao(self, share_url: str) -> dict:
        if not self.cookie:
            raise SphResolverError(ErrorCode.MISSING_COOKIE, await self._missing_cookie_message(share_url))

        self._emit_log("步骤 1/2: 通过腾讯元宝解析分享链接…")
        headers = dict(_YUANBAO_EXTRA_HEADERS)
        headers["cookie"] = self.cookie

        async with httpx.AsyncClient(timeout=30.0) as client:
            parse_resp = await self._post_json(
                client, YUANBAO_PARSE_URL,
                {"type": "video_channel_url", "url": share_url, "scene": 1},
                headers=headers, what="元宝解析接口",
            )

            data = parse_resp.get("data") or {}
            export_id = str(data.get("wx_export_id") or "").strip()
            playable_url = str(data.get("playable_url") or "")

            if not export_id and not playable_url:
                raise SphResolverError(
                    ErrorCode.COOKIE_INVALID,
                    "元宝解析接口未返回视频信息：Cookie 可能已失效或不是 yuanbao.tencent.com 的登录态，"
                    "请重新登录 https://yuanbao.tencent.com 后复制新的 Cookie 到 sph.cookie",
                )

            query = parse_qs(urlparse(playable_url).query)
            general_token = (query.get("token") or [""])[0]
            eid = (query.get("eid") or [""])[0] or export_id

            if not general_token:
                raise SphResolverError(
                    ErrorCode.COOKIE_INVALID,
                    "元宝解析接口返回的 playable_url 里没有 generalToken（播放令牌）："
                    "通常是 Cookie 已失效，请更新 sph.cookie 后重试",
                )

            self._emit_log("步骤 2/2: 获取视频号视频信息…")
            referer = (
                "https://channels.weixin.qq.com/finder-preview/pages/feed"
                "?entry_card_type=48&comment_scene=39&appid=0"
                f"&token={quote(general_token)}&entry_scene=0&eid={quote(eid)}"
            )
            headers = dict(_FEED_INFO_HEADERS)
            headers["Referer"] = referer
            api_url = FEED_INFO_URL + "?" + urlencode({
                "_rid": _generate_rid(),
                "_pageUrl": "https://channels.weixin.qq.com/finder-preview/pages/feed",
            })
            feed = await self._post_json(
                client, api_url,
                {"baseReq": {"generalToken": general_token}, "exportId": eid},
                headers=headers, what="视频号 feed 接口",
            )
            return feed

    # ---------------- 外部流程（复用 wx_channels_download 服务） ----------------

    async def _fetch_via_external(self, share_url: str) -> dict:
        """调用 wx_channels_download 的 /api/channels/parse_sph?url=...

        该项目（Go）能自动读取本机 Cookie，本工具只消费它返回的 feed JSON。
        响应体形如 {"code":0,"msg":"成功","data": <feed JSON>}。
        """
        url = f"{self.api_base}/api/channels/parse_sph?url={quote(share_url, safe='')}"
        headers = {}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise SphResolverError(
                ErrorCode.NETWORK,
                f"无法连接外部视频号解析服务（sph.api_base={self.api_base}）："
                f"{type(e).__name__}: {e}。请确认该服务正在运行",
            )
        if resp.status_code >= 400:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"外部视频号解析服务返回 HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            body = resp.json()
        except ValueError:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"外部视频号解析服务返回了非 JSON 内容: {resp.text[:200]}",
            )

        if isinstance(body, dict) and body.get("code") not in (None, 0):
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"外部视频号解析服务解析失败: {body.get('msg') or body.get('code')}",
            )
        data = body.get("data") if isinstance(body, dict) else None
        return data if isinstance(data, dict) else body

    # ---------------- 响应解析 ----------------

    def _build_info(self, payload: dict, share_url: str,
                    require_video: bool = True) -> SphVideoInfo:
        """把 feed JSON 转成 SphVideoInfo；结构不符/内容不可用时抛 SphResolverError"""
        if not isinstance(payload, dict):
            raise SphResolverError(ErrorCode.PARSE_FAILED,
                                   f"视频号接口返回了非预期内容: {str(payload)[:200]}")

        err_code = payload.get("errCode")
        if err_code not in (None, 0):
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"视频号接口返回 errCode={err_code}: {_plain_text(payload.get('errMsg')) or '无附加信息'}",
            )

        node = _find_feed(payload)
        if node is None:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                "视频号接口未返回 feedInfo（可能链接已失效或接口结构变化）",
            )

        err_msg = node.get("errMsg") or {}
        scene_info = node.get("sceneInfo") or {}

        # errMsg.type != 0 表示内容不可播放（常见于未登录、内容被限制、需在微信内观看）。
        # 这种情况下接口只返回 errMsg、不返回 feedInfo，必须先判它再取 feed。
        err_type = int(err_msg.get("type") or 0) if isinstance(err_msg, dict) else 0
        if err_type != 0:
            title = _plain_text(err_msg.get("title")) if isinstance(err_msg, dict) else ""
            content = _plain_text(err_msg.get("content")) if isinstance(err_msg, dict) else ""
            detail = "，".join(x for x in (title, content) if x) or f"errMsg.type={err_type}"
            raise SphResolverError(
                ErrorCode.CONTENT_UNAVAILABLE,
                f"视频号接口提示该内容暂时无法播放（{detail}）。"
                "常见原因：Cookie 已失效、内容仅限微信内观看、或作者限制了分享。"
                "可尝试更新 sph.cookie 后重试",
            )

        if "feedInfo" not in node:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                "视频号接口未返回 feedInfo（可能链接已失效或接口结构变化）",
            )

        feed_info = node.get("feedInfo") or {}
        author_info = node.get("authorInfo") or {}

        media_type = int(feed_info.get("mediaType") or 0)
        pic_info = feed_info.get("picInfo") or []
        if media_type == MEDIA_TYPE_PICTURE or (pic_info and not pick_video_url(feed_info)):
            raise SphResolverError(ErrorCode.NO_VIDEO,
                                   "该链接为视频号图文内容，本工具仅支持视频。")

        video_url = pick_video_url(feed_info)
        if require_video and not video_url:
            raise SphResolverError(
                ErrorCode.NO_VIDEO,
                "视频号接口未返回可下载的视频直链（feed 里没有 h264/videoUrl/h265 字段）",
            )

        description = str(feed_info.get("description") or "").strip()
        author = str(author_info.get("nickname") or "").strip()
        export_id = str(scene_info.get("dynamicExportId") or "").strip()

        stats = {
            "点赞": str(feed_info.get("likeCountFmt") or "").strip(),
            "评论": str(feed_info.get("commentCountFmt") or "").strip(),
            "转发": str(feed_info.get("forwardCountFmt") or "").strip(),
            "收藏": str(feed_info.get("favCountFmt") or "").strip(),
        }
        stats = {k: v for k, v in stats.items() if v}

        return SphVideoInfo(
            title=description or author or "视频号视频",
            author=author,
            description=description,
            video_url=video_url,
            cover_url=str(feed_info.get("coverUrl") or "").strip(),
            create_time=int(feed_info.get("createtime") or 0),
            media_type=media_type or MEDIA_TYPE_VIDEO,
            export_id=export_id,
            share_url=share_url,
            stats=stats,
            raw=payload,
        )

    # ---------------- 工具 ----------------

    async def _missing_cookie_message(self, share_url: str) -> str:
        """缺 Cookie 时，先免登录探一下元信息，让报错更具体"""
        info = None
        try:
            info = await self.probe_metadata(share_url)
        except Exception:
            info = None
        if info:
            who = f"，作者 {info.author}" if info.author else ""
            lead = f"分享链接本身有效（标题：{info.title}{who}），但下载视频需要登录态。"
        else:
            lead = "缺少下载视频所需的登录态。"
        return lead + _COOKIE_WHY + _COOKIE_HOW

    async def _post_json(self, client: httpx.AsyncClient, url: str, payload: dict,
                         headers: dict, what: str, raise_on_auth: bool = True) -> dict:
        """POST JSON 并统一处理状态码；错误信息带具体原因"""
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise SphResolverError(
                ErrorCode.NETWORK,
                f"请求{what}失败（网络错误）: {type(e).__name__}: {e}",
            )
        if resp.status_code in (401, 403):
            if raise_on_auth:
                raise SphResolverError(ErrorCode.COOKIE_INVALID, await self._auth_message(what, resp))
        elif resp.status_code >= 400:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"{what}返回 HTTP {resp.status_code}: {resp.text[:200]}",
            )
        try:
            return resp.json()
        except ValueError:
            raise SphResolverError(
                ErrorCode.PARSE_FAILED,
                f"{what}返回了非 JSON 内容（HTTP {resp.status_code}）: {resp.text[:200]}",
            )

    async def _auth_message(self, what: str, resp: httpx.Response) -> str:
        return (
            f"{what}返回 HTTP {resp.status_code}（未授权）。" + MISSING_COOKIE_HINT
        )
