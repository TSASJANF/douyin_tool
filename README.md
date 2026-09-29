# Douyin Tool · 抖音视频智能解析工具

[![License: MIT](https://img.shields.io/badge/License-MIT-18181B.svg)](./LICENSE)

整合抖音视频下载与 MiMo 视频解析，提取视频文案逐字稿。提供 **WebUI** 与 **命令行** 两种使用方式，完全自包含，clone 即用。

> 本项目仅供个人学习与内容研究使用，请遵守平台条款与相关法律法规。

## 功能特点

- **WebUI**：实时下载进度（速度/百分比/剩余时间）、步骤时间线、运行日志、历史记录浏览、视频在线播放、可视化配置管理
- **流式解析**：模型输出实时回显，思考过程默认折叠（可点击展开），正文边生成边显示
- **三种任务模式**：全流程（下载+解析）、仅下载（不消耗 API 额度）、仅解析（本地文件上传或视频直链）
- **临时参数**：解析任务可临时覆盖抽帧率/分辨率/提示词，仅当次任务生效，不改全局配置
- 自动下载抖音视频（1080P 保留，720P 直链送解析）
- **完全自包含**：链接解析模块内置，整个文件夹可任意搬移
- 提供 REST API 与 WebSocket 事件流，可供脚本集成

## 快速开始

```bash
git clone https://github.com/TSASJANF/douyin_tool.git
cd douyin_tool
pip install -r requirements.txt
python ctl.py start
```

浏览器打开 http://127.0.0.1:8000 —— 首次运行会自动生成 `config.json`（来自 `config.example.json`），到 **设置页**（或编辑 `config.json`）填入 MiMo API Key 即可开始使用。

> API Key 申请：https://platform.xiaomimimo.com/console
>
> WebUI 前端已预构建（`webui/dist/`），无需 Node.js；仅修改前端代码时才需要（见[前端开发](#前端开发可选)）。

## 服务启动 / 停止

推荐使用服务管理脚本（后台运行、日志落盘、健康检查、幂等安全）：

| 命令 | 说明 |
|------|------|
| `python ctl.py start` | 启动（可加 `--host 0.0.0.0 --port 9000`） |
| `python ctl.py stop` | 停止（校验进程身份，PID 文件丢失时按端口反查） |
| `python ctl.py restart` | 重启（未显式指定端口时沿用原端口） |
| `python ctl.py status` | 查询状态（退出码 0=运行中，3=未运行，便于脚本判断） |

Windows 下可双击 `start.bat` / `stop.bat` / `restart.bat`。

日志位置：`logs/webui.log`；托管信息：`.server.pid`；前台调试运行：`python web.py`。

## 使用方法

### WebUI（推荐）

| 页面 | 功能 |
|------|------|
| 视频解析 | 粘贴链接/口令 → 下载+解析全流程 → 实时进度 → 文案复制/下载 |
| 仅下载 | 只下载 1080P 视频，不调用 MiMo、不消耗 API 额度 |
| 仅解析 | 选择本地视频文件（上传）或粘贴视频直链，直接送 MiMo 解析 |
| 历史记录 | 浏览 output 目录、查看正文/视频信息、视频在线播放、文件下载 |
| 设置 | 可视化编辑 config.json（保存自动备份为 config.json.bak，对后续任务生效） |

两个解析页均有**临时解析参数**面板（默认折叠，点击展开）：可临时修改抽帧率、分辨率、分析提示词，仅对本次提交的任务生效，不改动全局 config.json；留空的项自动跟随全局设置。

注意：**仅解析-视频直链**模式下，直链必须可被 MiMo 服务端公网访问（如抖音 CDN 直链）；本地文件模式无此限制（走 base64 上传）。

### 命令行

```bash
python main.py
```

输入抖音链接/口令即可开始解析，行为与 WebUI 完全一致（共用同一处理流程）。

## 配置说明

编辑 `config.json`（或直接用 WebUI 设置页）。所有配置项：

#### mimo_api - API配置
| 参数 | 说明 | 默认值 | 调节建议 |
|------|------|--------|----------|
| `api_key` | API密钥 | 必填 | 申请地址见上文 |
| `base_url` | API地址 | `https://api.xiaomimimo.com/v1` | 一般不改 |
| `model` | 模型名称 | `mimo-v2.6-pro` | 全小写；可选 `mimo-v2.6-pro`/`mimo-v2.6-flash`/`mimo-v2.6-pro-ultraspeed`，`mimo-v2.5` 将于 2026-10-21 下线 |
| `max_completion_tokens` | 最大输出Token | `131072` | 模型硬上限 128K，超出会被 API 拒绝(400)，保存配置时也会被拦住 |
| `deep_thinking` | 深度思考 | `false` | **转写逐字稿务必保持关闭**：v2.6 系列开启后可能把整篇结果写进 `reasoning_content` 而正文返回空；开启后工具会自动关闭思考重试兜底 |
| `timeout` | API超时(秒) | `1800` | 短视频600，长视频1800 |

#### douyin - 下载配置
| 参数 | 说明 | 默认值 | 调节建议 |
|------|------|--------|----------|
| `download_dir` | 下载目录 | `output` | 相对于程序目录 |
| `max_retry` | 下载重试次数 | `3` | - |
| `video_quality` | 视频画质 | `highest` | 当前实际固定下载1080P |

#### video_analysis - 视频解析配置
| 参数 | 说明 | 默认值 | 调节建议 |
|------|------|--------|----------|
| `fps` | 抽帧率(每秒) | `6` | 文档范围 0.1~10；短视频2-3，长视频6-10，越高Token消耗越多 |
| `media_resolution` | 分辨率档次 | `default` | `default`平衡，`max`最高；其他值会被回退 default 并提示 |
| `prompt` | 分析提示词 | 逐字稿 | 可自定义提取方式 |

## 报错说明

所有失败都会给出**具体原因**（哪个环节、HTTP 状态码、服务端原始信息、出错参数、处理建议），不会只说"解析失败"：

- **保存配置**：非法值（如模型名拼错、`max_completion_tokens` 超过 131072、`fps` 超出 0.1~10）在写入前即被拒绝，并一次列出全部问题；
- **解析失败**：任务面板直接展示原因，常见如 `max_completion_tokens is too large`（超出模型输出上限）、`failed to download or process media content`（MiMo 服务端拉不到视频，直链过期或非公网可达）、`Invalid API Key`、`Unsupported model`（模型名必须全小写且在可用列表内）；
- **空正文但思考过程非空**：v2.6 系列开启深度思考时的已知现象（长视频转写任务上，模型把整篇结果写进 `reasoning_content` 后直接结束回合，`content` 为空）。关闭「深度思考」即可；工具在开启思考时也会自动关闭思考重试一次兜底；
- 参数越界时程序会按合法边界**自动钳制**并在日志中说明钳到了哪个值（如 `max_completion_tokens` 超过 131072 时按 131072 执行），任务不会被一个非法配置直接卡死。
- **不做分段拼接**：一次请求必须完整产出。若模型输出触及 `max_completion_tokens` 上限（`finish_reason=length`），工具不会把半截结果拼成“看似完整”的结果，而是在日志和结果中明确标注不完整，并提示调低 fps / 关闭深度思考后重试。
- **思考内容零泄漏**：最终结果只可能来自模型的 `content` 通道；若服务端把思考内容重复写入正文，会自动剔除并记日志；系统提示词已明确要求“只输出原始文案，不要前言/解释/思考过程”。
- **防“思考吞正文”**：系统提示词内含输出契约（结果必须写入正式回复正文、严禁只思考不输出）。v2.6 系列开思考时偶发“把完整结果写进 reasoning_content 后正文为空”，已通过提示词修复（实测 4/4 首轮即输出正文），并保留有上限的自动重试作为兜底。
- **空转（死循环）检测**：流式过程中实时监测——思考累计超 4000 字仍无正文、或正文同一段重复出现 3 次以上，即判定模型陷入重复空转：立即中断请求（不再干等）、清掉已流出的垃圾思考，并自动关闭深度思考重试；日志明确记录中断原因。
- 旧版 openai SDK（不支持 `max_completion_tokens`/`extra_body`/`stream`）会被自动检测并无缝切换到内置 HTTP 直连（基于项目已有依赖 httpx），**流式输出与深度思考开关不受影响**；如想走 SDK 原生通道，可执行 `python -m pip install -U openai`（非必需）。

## 输出文件

每个视频在 `output/视频标题/` 目录下：
- `视频标题_1080p.mp4` - 保留的原视频
- `info.txt` - 视频信息
- `正文.txt` - 解析出的文案

## 前端开发（可选）

仅当需要修改 WebUI 界面时：

```bash
cd webui
npm install
npm run dev        # Vite 开发服务器 http://localhost:5173（自动代理API到8000）
npm run build      # 构建到 webui/dist，之后 python ctl.py restart 即托管新版
```

## 项目结构

```
douyin_tool/
├── start.bat / stop.bat / restart.bat   # Windows 一键启停
├── ctl.py                     # 服务管理脚本（start/stop/restart/status）
├── main.py                    # CLI 入口
├── web.py                     # WebUI 服务入口（FastAPI + uvicorn）
├── config.json                # 本地配置（不入库，首次运行自动生成）
├── config.example.json        # 配置模板
├── modules/
│   ├── douyin_resolver/       # 内置的抖音链接解析包（自包含）
│   ├── douyin_downloader.py   # 下载器（支持进度事件回调）
│   └── video_analyzer.py      # MiMo 解析器（参数钳制 + 具体错误原因，支持事件回调）
├── server/                    # WebUI 后端
│   ├── app.py                 # FastAPI 应用（API + 前端托管）
│   ├── pipeline.py            # 处理流程：run_pipeline/run_download/run_parse（CLI/WebUI 共用）
│   ├── task_manager.py        # 后台任务、任务模式与临时参数覆盖
│   ├── config_validation.py   # 配置保存前的字段校验（具体错误原因）
│   └── api/                   # tasks / uploads / config / history / files 路由
├── webui/                     # 前端源码（Vite + React + Ant Design）
│   └── dist/                  # 预构建产物（由后端托管）
└── logs/webui.log             # 服务运行日志（不入库）
```

## REST API（供脚本调用）

- `POST /api/tasks` `{url, mode, source_type?, upload_id?, overrides?}` 创建任务
  - `mode`: `full`（下载+解析）/ `download`（仅下载）/ `parse`（仅解析）
  - `parse` 模式：`source_type=url` 时 `url` 为视频直链；`source_type=file` 时传 `upload_id`
  - `overrides`: `{fps?, media_resolution?, prompt?}` 任务级临时参数（可选）
- `PUT /api/uploads?filename=xxx` 原始流上传本地视频（body 为文件字节），返回 `{upload_id, filename, size}`
- `GET /api/tasks` / `GET /api/tasks/{id}` 任务列表/详情
- `WS /api/ws/tasks/{id}` 实时事件流（stage/download_progress/log/analysis_delta/done/error，其中 analysis_delta 携带 {reasoning|content} 增量文本）
- `GET /api/history` 历史记录；`GET /api/history/content?dir=&file=` 读文本
- `GET /api/files/download|stream?dir=&file=` 下载 / Range流式播放
- `GET/PUT /api/config` 配置读写
- 交互式文档：http://127.0.0.1:8000/docs

## License

[MIT](./LICENSE) © TSASJANF
