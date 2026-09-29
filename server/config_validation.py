"""
配置（config.json）保存前的校验。

设计原则：**错误必须一次说清**。所有问题一次性收集齐，写成人话
（哪个字段、当前值、合法范围/可选值、怎么改），由 API 层原样返回给前端展示，
避免把非法配置写进 config.json 后，直到调 API 报 400 才被发现。

字段与合法值以官方文档（mimo.mi.com）为准：
- 模型名必须全小写；v2.5 系列将于 2026-10-21 下线
- max_completion_tokens 上限 131072（v2.5/v2.6 全系最大输出 128K）
- fps 范围 [0.1, 10]（文档默认值 2）
- media_resolution 仅支持 default / max
"""

from typing import List

# 与 modules.video_analyzer 保持一致的常量（复制一份避免解析器被 server 反向依赖）
MODEL_MAX_COMPLETION_TOKENS = 131072
SUPPORTED_MODELS = (
    "mimo-v2.6-pro",
    "mimo-v2.6-flash",
    "mimo-v2.6-pro-ultraspeed",
    "mimo-v2.5",
)
MEDIA_RESOLUTIONS = ("default", "max")
FPS_RANGE = (0.1, 10)
TIMEOUT_RANGE = (60, 3600)
VIDEO_QUALITIES = ("highest", "1080p", "720p")


class ConfigValidationError(ValueError):
    """配置校验未通过；problems 为全部具体原因（每条都是完整可读的一句话）"""

    def __init__(self, problems: List[str]):
        self.problems = problems
        super().__init__("；".join(problems))


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_int_range(section: str, key: str, value, lo: int, hi: int,
                     unit: str, problems: List[str]):
    if not _is_number(value):
        problems.append(f"{section}.{key} 必须是数字，当前是 {value!r}")
        return
    if int(value) != value:
        problems.append(f"{section}.{key} 必须是整数，当前是 {value}")
        return
    if not (lo <= int(value) <= hi):
        problems.append(f"{section}.{key} 必须在 {lo}~{hi} {unit}之间，当前是 {int(value)}")


def validate_config(config: dict) -> None:
    """校验配置；不通过时抛出 ConfigValidationError（problems 含全部具体原因）"""
    problems: List[str] = []

    if not isinstance(config, dict):
        raise ConfigValidationError(["配置必须是一个 JSON 对象（形如 {\"mimo_api\": {...}}）"])

    # ---------- mimo_api ----------
    mimo = config.get("mimo_api")
    if not isinstance(mimo, dict):
        problems.append("缺少 mimo_api 配置段（应在其中填写 api_key / base_url / model 等）")
    else:
        api_key = mimo.get("api_key")
        if not isinstance(api_key, str) or not api_key.strip():
            problems.append("mimo_api.api_key 不能为空（申请地址 https://platform.xiaomimimo.com/console）")
        elif api_key.startswith("tp-"):
            problems.append("mimo_api.api_key 是 Token Plan Key（tp- 开头），"
                            "按量付费 API 请使用 sk- 开头的 Key，两者不可混用")

        base_url = mimo.get("base_url", "https://api.xiaomimimo.com/v1")
        if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
            problems.append(f"mimo_api.base_url 必须以 http:// 或 https:// 开头，当前是 {base_url!r}")

        model = mimo.get("model")
        if not isinstance(model, str) or not model.strip():
            problems.append("mimo_api.model 不能为空")
        else:
            model = model.strip()
            if model != model.lower():
                problems.append(f"mimo_api.model 必须全小写（官方要求）：{model!r} 应写成 {model.lower()!r}")
            if model.lower() not in SUPPORTED_MODELS:
                problems.append(
                    f"mimo_api.model 取值 {model!r} 不在可用列表中："
                    f"{'、'.join(SUPPORTED_MODELS)}（mimo-v2.5 将于 2026-10-21 下线，建议用 v2.6）")

        _check_int_range("mimo_api", "max_completion_tokens",
                         mimo.get("max_completion_tokens", MODEL_MAX_COMPLETION_TOKENS),
                         1, MODEL_MAX_COMPLETION_TOKENS, "", problems)
        if _is_number(mimo.get("max_completion_tokens")) and \
                int(mimo.get("max_completion_tokens")) > MODEL_MAX_COMPLETION_TOKENS:
            problems[-1] += f"（模型硬上限 128K，超出会被 API 以 400 拒绝）"

        _check_int_range("mimo_api", "timeout", mimo.get("timeout", 1800),
                         TIMEOUT_RANGE[0], TIMEOUT_RANGE[1], " 秒", problems)

        deep_thinking = mimo.get("deep_thinking", False)
        if not isinstance(deep_thinking, bool):
            if not (isinstance(deep_thinking, str)
                    and deep_thinking.strip().lower() in ("true", "false", "1", "0",
                                                          "yes", "no", "on", "off")):
                problems.append("mimo_api.deep_thinking 必须是布尔值 true/false，"
                                f"当前是 {deep_thinking!r}")

    # ---------- video_analysis ----------
    va = config.get("video_analysis")
    if not isinstance(va, dict):
        problems.append("缺少 video_analysis 配置段（应包含 fps / media_resolution / prompt）")
    else:
        fps = va.get("fps", 2)
        if not _is_number(fps):
            problems.append(f"video_analysis.fps 必须是数字，当前是 {fps!r}")
        elif not (FPS_RANGE[0] <= float(fps) <= FPS_RANGE[1]):
            problems.append(f"video_analysis.fps 必须在 {FPS_RANGE[0]}~{FPS_RANGE[1]} 之间"
                            f"（文档范围），当前是 {fps}")

        mr = va.get("media_resolution", "default")
        if mr not in MEDIA_RESOLUTIONS:
            problems.append(f"video_analysis.media_resolution 只能是 "
                            f"{' 或 '.join(MEDIA_RESOLUTIONS)}，当前是 {mr!r}")

        prompt = va.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            problems.append("video_analysis.prompt 不能为空（它决定模型如何提取文案）")

    # ---------- douyin ----------
    dy = config.get("douyin")
    if dy is not None and not isinstance(dy, dict):
        problems.append("douyin 必须是配置对象（download_dir / max_retry / video_quality）")
    elif isinstance(dy, dict):
        if dy.get("download_dir") is not None and \
                (not isinstance(dy["download_dir"], str) or not dy["download_dir"].strip()):
            problems.append("douyin.download_dir 不能为空")
        if dy.get("max_retry") is not None:
            _check_int_range("douyin", "max_retry", dy["max_retry"], 0, 10, " 次", problems)
        if dy.get("video_quality") is not None and dy["video_quality"] not in VIDEO_QUALITIES:
            problems.append(f"douyin.video_quality 只能是 "
                            f"{'、'.join(VIDEO_QUALITIES)}，当前是 {dy['video_quality']!r}")

    if problems:
        raise ConfigValidationError(problems)
