"""
视频解析模块
使用MiMo API分析视频内容，提取文案

支持事件回调：构造时传入 on_event(type, data) 可将日志转发给外部（如 WebUI）；
不传时保持原有 print 输出，CLI 行为不变。

错误可读性设计（重要）：
- 任何失败都会在 self.last_error 里留下「具体原因」：HTTP 状态码、服务端原始错误信息、
  出错参数，以及对应的处理建议；pipeline 会把它直接透传给最终错误提示。
- 入参（模型名 / max_completion_tokens / fps / media_resolution）在构造时即校验并钳制，
  越界时会明确告知被钳到了哪个合法值，而不是等 API 报 400 再去猜。
- 已知坑（2026-09 实测，v2.6-pro）：深度思考默认开启时，遇到「长视频+稠密语音转写」
  这类任务，模型会把整篇结果写进 reasoning_content 后直接结束回合，content 返回空
  （finish_reason=stop）。本模块默认关闭深度思考，并在开启状态下遇到空正文时
  自动关闭思考重试一次，避免把可成功的任务判失败。
"""

import os
import base64
import inspect
import json as _json
import mimetypes
from pathlib import Path
from typing import Optional, Callable, List

import httpx
from openai import OpenAI

try:  # openai>=1.0 的细粒度异常（用于给出具体原因）
    from openai import APIStatusError, APIConnectionError, APITimeoutError, APIError
except ImportError:  # pragma: no cover - 极旧版本没有这些异常类
    APIStatusError = APIConnectionError = APITimeoutError = APIError = ()

EventCallback = Callable[[str, dict], None]

# ---- 模型能力上限（来源：mimo.mi.com 文档「视频理解 / 模型列表」）----
MODEL_MAX_COMPLETION_TOKENS = 131072   # v2.5 / v2.6 全系最大输出 128K
MAX_VIDEO_URL_MB = 300                 # URL 方式单个视频上限 300MB
MAX_VIDEO_BASE64_MB = 50               # Base64 方式编码字符串上限 50MB
FPS_RANGE = (0.1, 10)                  # 文档：fps 默认 2，范围 [0.1, 10]
MEDIA_RESOLUTIONS = ("default", "max")
SUPPORTED_MODELS = (
    "mimo-v2.6-pro",
    "mimo-v2.6-flash",
    "mimo-v2.6-pro-ultraspeed",
    "mimo-v2.5",
)

DEFAULT_MODEL = "mimo-v2.5"

# ---- 空转（死循环）检测阈值 ----
THINKING_LOOP_GUARD_CHARS = 4000   # 思考累计超过该字数仍未产出正文 → 判定空转
CONTENT_LOOP_GUARD = 3             # 同一段正文重复出现的次数上限
CONTENT_LOOP_CHECK_EVERY = 40      # 每收到多少个正文增量包做一次重复检测


class _LoopAbort(Exception):
    """内部信号：检测到模型重复空转，中断当前流式请求"""

    def __init__(self, kind: str, detail):
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind} loop: {detail}")


# ---------------- 内置 HTTP 直连（SDK 过旧时的兜底传输） ----------------

class MiMoAPIError(Exception):
    """
    原始 HTTP 传输的错误，与 openai.APIStatusError 同构，
    这样两条传输通道的错误都能走同一套「具体原因」格式化。
    """

    def __init__(self, status_code: int, body, message: str = ""):
        self.status_code = status_code
        self.body = body if isinstance(body, dict) else {}
        err = self.body.get("error") if isinstance(self.body.get("error"), dict) else self.body
        self.code = err.get("code")
        self.param = err.get("param")
        super().__init__(message or err.get("message") or "")


class _RawMessage:
    """统一 message/delta 的字段访问（content / reasoning_content）"""

    def __init__(self, d: dict):
        d = d or {}
        self.content = d.get("content")
        self.reasoning_content = d.get("reasoning_content")


class _RawChoice:
    def __init__(self, c: dict):
        c = c or {}
        self.message = _RawMessage(c.get("message"))
        self.delta = _RawMessage(c.get("delta"))
        self.finish_reason = c.get("finish_reason")


class _RawResponse:
    """把服务端 JSON 包装成与 SDK 响应同构的对象"""

    def __init__(self, raw: dict):
        raw = raw or {}
        self.choices = [_RawChoice(c) for c in (raw.get("choices") or [])]


class _RawStream:
    """SSE 流式响应迭代器：逐行解析 data: {...}，结束时释放连接"""

    def __init__(self, client: httpx.Client, response: httpx.Response):
        self._client = client
        self._response = response

    def __iter__(self):
        try:
            for line in self._response.iter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    raw = _json.loads(data)
                except ValueError:
                    continue
                if isinstance(raw, dict) and raw.get("error"):
                    raise MiMoAPIError(200, raw)
                yield _RawResponse(raw)
        finally:
            self._response.close()
            self._client.close()


def _safe_json(text: str) -> dict:
    try:
        return _json.loads(text)
    except ValueError:
        return {"message": text[:500]}


class VideoAnalyzer:
    """视频解析器"""

    def __init__(self, mimo_config: dict, analysis_config: dict,
                 on_event: Optional[EventCallback] = None):
        self.api_key = mimo_config.get("api_key")
        self.base_url = mimo_config.get("base_url", "https://api.xiaomimimo.com/v1")
        self.model = mimo_config.get("model", DEFAULT_MODEL)
        self.on_event = on_event
        self.client = None
        self.last_error: Optional[str] = None
        self._sdk_ready = True          # SDK 参数不受支持时自动切到内置 HTTP 直连
        self.finish_reason: Optional[str] = None
        self.continued_rounds = 0
        try:
            from openai import __version__ as _openai_version
        except Exception:  # pragma: no cover
            _openai_version = "未知版本"
        self._openai_version = _openai_version

        warnings: List[str] = []

        # ---- 模型名：必须全小写，且应是已知型号 ----
        if not isinstance(self.model, str) or not self.model.strip():
            self.model = DEFAULT_MODEL
            warnings.append(f"未配置模型名，已按默认 {DEFAULT_MODEL} 执行")
        elif self.model != self.model.lower():
            fixed = self.model.lower()
            warnings.append(f"模型名必须全小写（官方要求）：'{self.model}' 已按 '{fixed}' 执行")
            self.model = fixed
        if self.model not in SUPPORTED_MODELS:
            warnings.append(
                f"模型名 '{self.model}' 不在已知列表（{'、'.join(SUPPORTED_MODELS)}）中，"
                "若 API 返回 404 / model not found，请到设置页改用下拉列表中的模型"
            )

        # ---- 深度思考开关：默认关闭 ----
        # 原因：提取逐字稿是「转写」任务，开启思考后 v2.6 系列可能把整篇结果写进
        # reasoning_content 而 content 返回空；且思考内容会占用 max_completion_tokens 预算。
        raw_thinking = mimo_config.get("deep_thinking", False)
        self.deep_thinking = bool(raw_thinking) if isinstance(raw_thinking, bool) \
            else str(raw_thinking).strip().lower() in ("1", "true", "yes", "on", "enabled")
        if self.deep_thinking:
            warnings.append(
                "已开启深度思考（deep_thinking=true）：若模型把结果全部写入思考过程导致正文为空，"
                "本工具会自动关闭思考重试一次；提取逐字稿建议关闭思考（更快、更省 Token）")

        # ---- 最大输出 Token：钳到模型硬上限 ----
        raw_tokens = mimo_config.get("max_completion_tokens", MODEL_MAX_COMPLETION_TOKENS)
        try:
            raw_tokens = int(raw_tokens)
        except (TypeError, ValueError):
            raw_tokens = MODEL_MAX_COMPLETION_TOKENS
            warnings.append(
                f"max_completion_tokens 不是有效数字，已按模型上限 {MODEL_MAX_COMPLETION_TOKENS} 执行")
        tokens = max(1, min(raw_tokens, MODEL_MAX_COMPLETION_TOKENS))
        if tokens != raw_tokens:
            warnings.append(
                f"max_completion_tokens={raw_tokens} 超过模型硬上限 {MODEL_MAX_COMPLETION_TOKENS}"
                f"（超出会被 API 以 400 拒绝），已自动按 {MODEL_MAX_COMPLETION_TOKENS} 执行；"
                "如需长期生效，请到设置页把该值改到 131072 以内")
        self.max_tokens = tokens

        # ---- 超时 ----
        try:
            self.timeout = float(mimo_config.get("timeout", 1800) or 1800)
        except (TypeError, ValueError):
            self.timeout = 1800.0
            warnings.append("mimo_api.timeout 不是有效数字，已按 1800 秒执行")
        if self.timeout <= 0:
            self.timeout = 1800.0

        # ---- 抽帧率：钳到文档范围 [0.1, 10] ----
        fps = analysis_config.get("fps", 6)
        try:
            fps = float(fps)
        except (TypeError, ValueError):
            fps = 6.0
            warnings.append("video_analysis.fps 不是有效数字，已按默认 6 执行")
        fps_clamped = max(FPS_RANGE[0], min(fps, FPS_RANGE[1]))
        if fps_clamped != fps:
            warnings.append(
                f"fps={fps} 超出文档允许范围 [{FPS_RANGE[0]}, {FPS_RANGE[1]}]，"
                f"已按 {fps_clamped} 执行")
        self.fps = fps_clamped

        # ---- 分辨率档次：非法值回退 default ----
        mr = analysis_config.get("media_resolution", "default")
        if mr not in MEDIA_RESOLUTIONS:
            warnings.append(
                f"media_resolution='{mr}' 非法（仅支持 {'、'.join(MEDIA_RESOLUTIONS)}），"
                "已按 'default' 执行")
            mr = "default"
        self.media_resolution = mr

        self.prompt = analysis_config.get("prompt", "一字不差地提取完整文案")

        self._emit_log("MiMo 解析参数检查：")
        for w in warnings or ["模型 / 输出上限 / 抽帧率 / 分辨率均在合法范围内"]:
            self._emit_log(f"  - {w}")

        if self.api_key:
            self.client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0
            )
        else:
            self._emit_log("错误: 未配置 MiMo API Key（mimo_api.api_key），无法调用解析")

    # ---------------- 基础输出 ----------------

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
            ".wmv": "video/x-wmv"
        }
        return mime_map.get(ext, "video/mp4")

    def _file_to_base64(self, file_path: str) -> str:
        """将文件转换为Base64编码"""
        with open(file_path, "rb") as f:
            data = f.read()
        return base64.b64encode(data).decode("utf-8")

    # ---------------- 错误原因格式化 ----------------

    def _hint_for_api_error(self, status: Optional[int], message: str, param: str) -> str:
        """把服务端常见错误翻译成「人话 + 处理建议」"""
        m = (message or "").lower()
        p = (param or "").lower()

        if "max_completion_tokens" in m and "too large" in m:
            return (f"配置项 mimo_api.max_completion_tokens 超过了模型硬上限 "
                    f"{MODEL_MAX_COMPLETION_TOKENS}（本次已自动按上限执行，请到设置页修正）")
        if "failed to download or process media content" in m or "failed to download" in p:
            return ("MiMo 服务端无法下载/解码该视频。URL 方式要求公网可访问且不超过 "
                    f"{MAX_VIDEO_URL_MB}MB（抖音直链可能已过期，可重试或改用本地文件上传）；"
                    f"Base64 方式要求编码后不超过 {MAX_VIDEO_BASE64_MB}MB，"
                    "格式限 MP4/MOV/AVI/WMV")
        if "thinking" in m:
            return ("服务端不接受 thinking 参数（该模型可能未开放深度思考开关）。"
                    "请把设置页的「深度思考」关掉后重试")
        if status in (401, 403) or "api key" in m or "unauthorized" in m or "invalid_key" in m:
            return "API Key 无效、过期或无权访问该模型，请到设置页检查 mimo_api.api_key"
        if any(k in m for k in ("unsupported model", "model_not_found", "model not found",
                                "does not exist", "invalid model")) or status == 404:
            return (f"模型名不存在或拼写错误（必须全小写）。可用模型：{'、'.join(SUPPORTED_MODELS)}；"
                    f"当前配置为 '{self.model}'")
        if status == 429 or "rate limit" in m or "quota" in m or "insufficient" in m:
            return "触发限流或额度不足，请稍后重试，或到控制台查看用量与额度"
        if ("context" in m and "length" in m) or "too many tokens" in m:
            return ("视频 Token 超出模型上下文上限，请降低 fps 或把 media_resolution 改为 default，"
                    "或改传更短的视频")
        if param:
            return f"出错的请求参数：{param}，请按上方服务端信息修正后重试"
        return "请对照上方服务端原始信息检查配置与输入"

    def _describe_api_error(self, e: Exception) -> str:
        """把异常格式化为带具体原因的说明（同时兼容 SDK 异常与内置直连的 MiMoAPIError）"""
        status = getattr(e, "status_code", None)
        body = getattr(e, "body", None)
        if status is not None or isinstance(e, MiMoAPIError):
            # 服务端错误体有两种形态：{"error": {...}} 或直接 {"code","message","param"}
            err = {}
            if isinstance(body, dict):
                err = body.get("error") if isinstance(body.get("error"), dict) else body
            code = getattr(e, "code", None) or err.get("code")
            message = err.get("message") or ""
            param = err.get("param") or getattr(e, "param", None) or ""
            if not message:
                message = (str(e) or "").strip()
            head = f"MiMo API 返回错误 HTTP {status or '?'}"
            text = f"{head}: {message}" if message else head
            if param:
                text += f"；出错参数: {param}"
            hint = self._hint_for_api_error(status, message, param)
            return f"{text}。{hint}" if hint else text

        if APIConnectionError and isinstance(e, APIConnectionError):
            return (f"无法连接 MiMo API（{self.base_url}）：{e.__class__.__name__}: {e}。"
                    "请检查网络连通性、代理设置，以及 mimo_api.base_url 是否正确")
        if APITimeoutError and isinstance(e, APITimeoutError):
            return (f"调用 MiMo API 超时（mimo_api.timeout={self.timeout:.0f} 秒）。"
                    "长视频解析耗时更久，可适当加大超时时间后重试")
        if isinstance(e, httpx.TimeoutException):
            return (f"调用 MiMo API 超时（mimo_api.timeout={self.timeout:.0f} 秒）。"
                    "长视频解析耗时更久，可适当加大超时时间后重试")
        if isinstance(e, httpx.HTTPError):
            return (f"无法连接 MiMo API（{self.base_url}）：{e.__class__.__name__}: {e}。"
                    "请检查网络连通性、代理设置，以及 mimo_api.base_url 是否正确")
        if APIError and isinstance(e, APIError):
            return f"MiMo API 调用失败（{e.__class__.__name__}）: {e}"
        return f"调用 MiMo API 时发生异常（{e.__class__.__name__}）: {e}"

    # ---------------- 请求构造 ----------------

    def _build_messages(self, video_url: str) -> list:
        return [
            {"role": "system", "content":
                "你是视频分析专家，特点是不会遗漏视频的任何一个细节。\n"
                "【输出契约 · 必须遵守】\n"
                "1. 最终结果必须作为正式回复完整输出：即使你已经在思考过程中得出结论，"
                "也必须把结果写进回复正文，不允许只放在思考里；\n"
                "2. 严禁出现“只有思考过程、正文为空”的回复；\n"
                "3. 正文中不要添加与结果无关的前言、说明、总结、小标题或时间标注，直接给出结果本身；\n"
                "4. 严禁重复输出：每一段、每一句只输出一次。一旦察觉自己在重复已经写过的内容，"
                "立即停止重复，继续未完成的部分或直接结束，禁止循环复述；\n"
                "5. 思考过程同样只做推进，不要反复复述、复盘已经完成的同一段内容；"
                "转写类任务不需要冗长思考，思考变长时优先输出结果，不要继续空想。"},
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
        ]

    def _create_completion(self, messages: list, thinking: bool, stream: bool = False):
        """
        发起 chat.completions 请求。
        thinking=False 且 stream=False 时返回完整响应对象；stream=True 时返回增量流。
        异常不在此处吞掉，由调用方转成带具体原因的 last_error。

        传输选择：openai SDK 能用（参数都支持）时走 SDK；否则自动切到内置 HTTP 直连
        （httpx），保证 thinking / max_completion_tokens / stream 三个参数真正发到服务端——
        旧版 SDK 会以 TypeError 静默丢掉这些参数，曾导致「深度思考开关不生效、流式被降级」。
        """
        if self._sdk_ready and self._sdk_missing_params(stream):
            missing = self._sdk_missing_params(stream)
            self._emit_log(
                f"当前 openai 客户端（{self._openai_version}）不支持参数：{'、'.join(missing)}，"
                "已自动切换到内置 HTTP 直连（功能完全一致：流式输出与深度思考开关均正常生效）")
            self._sdk_ready = False

        if self._sdk_ready:
            try:
                return self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_completion_tokens=self.max_tokens,
                    stream=stream,
                    extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}}
                )
            except TypeError:
                # 运行期才发现不兼容（例如签名里有 **kwargs 但实际拒绝）：切换直连
                self._emit_log(
                    f"当前 openai 客户端（{self._openai_version}）拒绝了本次请求参数，"
                    "已自动切换到内置 HTTP 直连")
                self._sdk_ready = False

        return self._raw_request(messages, thinking, stream)

    def _sdk_missing_params(self, stream: bool) -> List[str]:
        """检查 SDK 的 create() 是否支持所需参数；签名探测失败时视为可用（由运行期兜底）"""
        try:
            params = inspect.signature(self.client.chat.completions.create).parameters
        except (TypeError, ValueError):
            return []
        needed = ["max_completion_tokens", "extra_body"]
        if stream:
            needed.append("stream")
        return [n for n in needed if n not in params]

    def _raw_request(self, messages: list, thinking: bool, stream: bool):
        """内置 HTTP 直连（httpx），不依赖 openai SDK 版本"""
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "messages": messages,
            "max_completion_tokens": self.max_tokens,
            "stream": stream,
            "thinking": {"type": "enabled" if thinking else "disabled"},
        }
        client = httpx.Client(timeout=self.timeout)
        try:
            request = client.build_request("POST", url, json=body, headers=headers)
            response = client.send(request, stream=stream)
            if response.status_code != 200:
                text = response.read().decode("utf-8", "ignore")
                raise MiMoAPIError(response.status_code, _safe_json(text))
            if stream:
                # 流式：连接生命周期交给 _RawStream（迭代结束后统一关闭）
                return _RawStream(client, response)
            try:
                return _RawResponse(_safe_json(response.text))
            finally:
                client.close()
        except BaseException:
            # 注意：不能用 `with client:`——send() 已把 client 置为 OPENED，
            # 再进入上下文会触发 httpx 的 "Cannot open a client instance more than once"
            client.close()
            raise

    # ---------------- 流式增量推送 ----------------

    def _emit_delta(self, kind: str, text: str):
        """把一段增量文本推给外部（WebUI 实时渲染）；CLI 模式下静默"""
        if self.on_event and text:
            self.on_event("analysis_delta", {kind: text})

    # ---------------- 结果处理 ----------------

    def _msg_content(self, response) -> Optional[str]:
        """安全取出 choices[0].message.content"""
        if response is None or not getattr(response, "choices", None):
            return None
        return getattr(response.choices[0].message, "content", None)

    def _msg_reasoning(self, response) -> str:
        if response is None or not getattr(response, "choices", None):
            return ""
        return getattr(response.choices[0].message, "reasoning_content", None) or ""

    def _finish_reason(self, response) -> str:
        if response is None or not getattr(response, "choices", None):
            return "未知"
        return getattr(response.choices[0], "finish_reason", None) or "未知"

    def _analyze(self, video_url: str, what: str) -> Optional[str]:
        """
        流式解析：实时推送思考过程与正文增量；失败原因写入 self.last_error。
        """
        reasoning_parts: List[str] = []
        content_parts: List[str] = []
        finish_reason = "未知"
        reasoning_len = 0
        content_deltas_since_check = 0

        try:
            stream = self._create_completion(self._build_messages(video_url),
                                             thinking=self.deep_thinking, stream=True)
            for chunk in stream:
                if not getattr(chunk, "choices", None):
                    continue
                choice = chunk.choices[0]
                fr = getattr(choice, "finish_reason", None)
                if fr:
                    finish_reason = fr
                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue
                r_delta = getattr(delta, "reasoning_content", None) or ""
                c_delta = getattr(delta, "content", None) or ""
                if r_delta:
                    reasoning_parts.append(r_delta)
                    reasoning_len += len(r_delta)
                    self._emit_delta("reasoning", r_delta)
                    # 空转检测：思考了半天一个字正文都没有 → 中断，交给下方恢复逻辑
                    if not content_parts and reasoning_len > THINKING_LOOP_GUARD_CHARS:
                        raise _LoopAbort("thinking", reasoning_len)
                if c_delta:
                    content_parts.append(c_delta)
                    self._emit_delta("content", c_delta)
                    content_deltas_since_check += 1
                    if content_deltas_since_check >= CONTENT_LOOP_CHECK_EVERY:
                        content_deltas_since_check = 0
                        text_so_far = "".join(content_parts)
                        tail = text_so_far[-120:]
                        if len(tail) >= 120 and \
                                text_so_far.count(tail) >= CONTENT_LOOP_GUARD:
                            raise _LoopAbort("content", len(text_so_far))
        except _LoopAbort as loop:
            if loop.kind == "thinking":
                self._emit_log(
                    f"警告: 思考过程已累计 {loop.detail} 字仍未产出任何正文，"
                    "判定模型陷入重复空转，已中断本次请求（不再等待它自己停下）")
                # 清掉面板里已经流式堆出来的空转思考，别让用户看一堆垃圾
                if self.on_event:
                    self.on_event("analysis_reset", {"reasoning": True})
                # 有思考无正文 → 走统一的“关思考重试”恢复
                return self._handle_empty("".join(reasoning_parts), "loop", video_url, what)
            self.last_error = (
                f"{what}：检测到模型在正文里重复输出同一段内容"
                f"（{loop.detail} 字内同一段重复出现 {CONTENT_LOOP_GUARD} 次以上），"
                "已中断请求。这是模型的重复退化，请重试；若反复出现，请关闭「深度思考」")
            self._emit_log(f"错误: {self.last_error}")
            return None
        except TypeError:
            # 旧版 SDK 不支持流式：_create_completion 内部已降级为一次性返回
            response = self._create_completion(self._build_messages(video_url),
                                               thinking=self.deep_thinking, stream=False)
            content = self._msg_content(response)
            if content and content.strip():
                return self._finalize(content, self._msg_reasoning(response),
                                      self._finish_reason(response), video_url, what)
            return self._handle_empty(self._msg_reasoning(response),
                                      self._finish_reason(response), video_url, what)
        except Exception as e:
            self.last_error = f"{what}: {self._describe_api_error(e)}"
            self._emit_log(f"错误: {self.last_error}")
            return None

        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        if content.strip():
            return self._finalize(content, reasoning, finish_reason, video_url, what)
        return self._handle_empty(reasoning, finish_reason, video_url, what)

    # ---------------- 结果收尾：截断续写 + 思考隔离 ----------------

    def _finalize(self, content: str, reasoning: str, finish_reason: str,
                  video_url: str, what: str) -> Optional[str]:
        """
        正常出稿前的收尾：思考内容隔离 + 完整性记录。
        不做"续写"式的拼接——一次请求必须完整产出；
        若 finish_reason=length（确实撞了输出上限），如实记录并向用户报告，由用户决定如何处理。
        """
        content = self._strip_reasoning_leak(content, reasoning)
        self.finish_reason = finish_reason
        self._emit_log(f"视频分析完成！正文 {len(content)} 字（finish_reason={finish_reason}）")
        if finish_reason == "length":
            self._emit_log(
                "警告: 输出达到了 max_completion_tokens 上限，正文不完整。"
                "请到设置页调低 fps / 关闭深度思考 / 或减小单次视频长度后重试；"
                "本工具不做分段续写，避免把半截结果拼成看似完整的结果")
        return content

    def _strip_reasoning_leak(self, content: str, reasoning: str) -> str:
        """
        硬保证：思考内容绝不进入最终结果。
        content 只应来自 content 通道；若个别网关把 reasoning 重复塞进了 content
        （表现为 content 以 reasoning 开头），去掉重复部分并记录日志。
        """
        if reasoning and content and reasoning[:80] and reasoning[:80] in content:
            idx = content.find(reasoning[:80])
            self._emit_log("警告: 检测到服务端把思考内容重复写入了正文，已自动剔除重复部分")
            content = content[:idx] + content[idx + len(reasoning[:80]):]
        return content.strip()

    def _handle_empty(self, reasoning: str, finish_reason: str, video_url: str,
                      what: str) -> Optional[str]:
        # 已知坑：思考开启时，v2.6 可能把整篇结果写进 reasoning_content，content 返回空。
        if reasoning.strip() and self.deep_thinking:
            if finish_reason == "loop":
                self._emit_log("思考空转已中断，正在自动关闭深度思考重试…")
            else:
                self._emit_log(
                    "警告: 模型把全部输出写入了思考过程(reasoning_content)、正文为空"
                    f"（finish_reason={finish_reason}）——长视频转写任务在开启深度思考时"
                    "会出现该现象。正在自动关闭深度思考重试一次…")
            try:
                response = self._create_completion(self._build_messages(video_url),
                                                   thinking=False, stream=False)
                content = self._msg_content(response)
                if content and content.strip():
                    self._emit_log("重试成功：关闭深度思考后模型正常返回了正文")
                    content = self._strip_reasoning_leak(content, self._msg_reasoning(response))
                    fr2 = self._finish_reason(response)
                    self.finish_reason = fr2
                    self._emit_log(f"重试成功：关闭深度思考后模型正常返回了正文（{len(content)} 字）")
                    if fr2 == "length":
                        self._emit_log("警告: 重试结果同样达到输出上限，正文不完整"
                                       "（请调低 fps 或关闭深度思考后重试）")
                    self._emit_delta("content", content)   # 一次性把最终正文推给前端
                    return content
                reasoning = self._msg_reasoning(response) or reasoning
                finish_reason = self._finish_reason(response)
            except Exception as e:
                self._emit_log(f"自动重试也未成功: {self._describe_api_error(e)}")

        if finish_reason == "length":
            self.last_error = (
                f"{what}：模型没有产出正文——输出在达到 max_completion_tokens"
                f"（{self.max_tokens}）上限时被截断，且额度被思考过程占满。"
                "可尝试：调低 fps / 把 media_resolution 改为 default，"
                "或在设置页关闭「深度思考」，给正文留出输出空间")
        elif reasoning.strip():
            self.last_error = (
                f"{what}：MiMo API 返回了空正文（finish_reason={finish_reason}），"
                f"但思考过程非空（{len(reasoning)} 字）——模型把结果写进了 reasoning_content "
                "却没有生成正文。这是开启深度思考时的已知现象（v2.6 系列在长视频转写任务上尤为明显）。"
                "处理办法：到设置页关闭「深度思考」后重试；本工具已自动重试过一次（关闭思考）仍未成功，"
                "请手动关闭后重试，或换用 mimo-v2.5")
        else:
            self.last_error = (
                f"{what}：MiMo API 返回了空内容（finish_reason={finish_reason}）且无思考过程。"
                "可重试；若始终为空，请检查提示词或更换模型")
        self._emit_log(f"错误: {self.last_error}")
        return None

    # ---------------- 对外入口 ----------------

    def analyze_local_video(self, video_path: str) -> Optional[str]:
        """
        分析本地视频文件（Base64 方式传入）

        返回: 提取的文案内容 或 None（失败原因见 self.last_error）
        """
        self.last_error = None
        self.finish_reason = None
        self.continued_rounds = 0
        if not self.client:
            self.last_error = "MiMo API 未配置（mimo_api.api_key 为空），无法调用解析"
            self._emit_log(f"错误: {self.last_error}")
            return None

        if not os.path.exists(video_path):
            self.last_error = f"视频文件不存在: {video_path}"
            self._emit_log(f"错误: {self.last_error}")
            return None

        file_size = os.path.getsize(video_path)
        self._emit_log(f"视频文件大小: {file_size / (1024*1024):.2f} MB")
        if file_size > MAX_VIDEO_BASE64_MB * 1024 * 1024:
            self.last_error = (f"本地文件 {file_size/1024/1024:.1f}MB 超过 Base64 方式上限 "
                               f"{MAX_VIDEO_BASE64_MB}MB，请压缩视频或改用「视频直链」方式解析")
            self._emit_log(f"错误: {self.last_error}")
            return None

        try:
            self._emit_log("正在编码视频文件...")
            base64_data = self._file_to_base64(video_path)
            mime_type = self._get_mime_type(video_path)
            video_url = f"data:{mime_type};base64,{base64_data}"

            self._emit_log("正在调用MiMo API分析视频...")
            self._emit_log(f"模型: {self.model}, FPS: {self.fps}, 分辨率: {self.media_resolution}, "
                           f"最大输出Token: {self.max_tokens}, 深度思考: "
                           f"{'开' if self.deep_thinking else '关'}")
            return self._analyze(video_url, f"本地视频解析失败（{Path(video_path).name}）")

        except Exception as e:
            self.last_error = (f"本地视频解析失败（{Path(video_path).name}）: "
                               f"{self._describe_api_error(e)}")
            self._emit_log(f"错误: {self.last_error}")
            return None

    def analyze_remote_video(self, video_url: str) -> Optional[str]:
        """
        分析远程视频链接（URL 方式传入）

        返回: 提取的文案内容 或 None（失败原因见 self.last_error）
        """
        self.last_error = None
        self.finish_reason = None
        self.continued_rounds = 0
        if not self.client:
            self.last_error = "MiMo API 未配置（mimo_api.api_key 为空），无法调用解析"
            self._emit_log(f"错误: {self.last_error}")
            return None

        try:
            self._emit_log("正在调用MiMo API分析远程视频...")
            self._emit_log(f"模型: {self.model}, FPS: {self.fps}, 分辨率: {self.media_resolution}, "
                           f"最大输出Token: {self.max_tokens}, 深度思考: "
                           f"{'开' if self.deep_thinking else '关'}")
            return self._analyze(video_url, "远程视频解析失败")

        except Exception as e:
            self.last_error = f"远程视频解析失败: {self._describe_api_error(e)}"
            self._emit_log(f"错误: {self.last_error}")
            return None
