"""
后台解析任务管理

- 任务在 asyncio 后台运行，并发上限 max_concurrent
- 事件（stage/log/download_progress/done/error）扇出到各订阅者队列（WebSocket）
- log/stage 保留历史、进度只保留最新快照，重连时通过 snapshot 补发
"""

import asyncio
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from . import config_store
from .pipeline import run_pipeline, run_download, run_parse, PipelineError

MAX_LOGS = 300          # 每任务保留的日志条数上限
MAX_TASKS_KEPT = 50     # 内存中保留的任务数上限

# 允许按任务临时覆盖的 video_analysis 参数白名单
OVERRIDE_KEYS = {"fps", "media_resolution", "prompt"}


@dataclass
class Task:
    id: str
    url: str                       # 展示用输入（链接/文件名等）
    mode: str = "full"             # full: 下载+解析 / download: 仅下载 / parse: 仅解析
    source_type: str | None = None  # parse 模式: url / file
    parse_source: str | None = None  # parse 模式: 服务端文件路径或直链URL
    overrides: dict | None = None   # 临时参数覆盖 {fps?, media_resolution?, prompt?}
    status: str = "pending"
    title: str = ""
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    stage: Optional[Dict[str, Any]] = None
    progress: Optional[Dict[str, Any]] = None
    logs: List[str] = field(default_factory=list)
    analysis: Dict[str, str] = field(default_factory=lambda: {"reasoning": "", "content": ""})
    result: Optional[Dict[str, Any]] = None
    subscribers: List[asyncio.Queue] = field(default_factory=list)
    aio_task: Optional[asyncio.Task] = None


class TaskManager:
    def __init__(self, max_concurrent: int = 2):
        self._tasks: Dict[str, Task] = {}
        self._sem = asyncio.Semaphore(max_concurrent)

    # ---------- 查询 ----------

    def get(self, task_id: str) -> Optional[Task]:
        return self._tasks.get(task_id)

    def list_all(self) -> List[Task]:
        # 新任务在前
        return sorted(self._tasks.values(), key=lambda t: t.created_at, reverse=True)

    def view(self, task: Task, detail: bool = False) -> dict:
        data = {
            "id": task.id,
            "url": task.url,
            "mode": task.mode,
            "source_type": task.source_type,
            "status": task.status,
            "title": task.title,
            "error": task.error,
            "created_at": task.created_at,
            "started_at": task.started_at,
            "finished_at": task.finished_at,
            "stage": task.stage,
            "progress": task.progress,
        }
        if detail:
            data["logs"] = task.logs
            data["result"] = task.result
            data["analysis"] = task.analysis
        return data

    # ---------- 创建与运行 ----------

    def create(self, url: str, mode: str = "full", source_type: Optional[str] = None,
               parse_source: Optional[str] = None, overrides: Optional[dict] = None) -> Task:
        task = Task(
            id=uuid.uuid4().hex[:12],
            url=url.strip(),
            mode=mode,
            source_type=source_type,
            parse_source=parse_source,
            overrides={k: v for k, v in (overrides or {}).items()
                       if k in OVERRIDE_KEYS and v is not None} or None,
        )
        self._tasks[task.id] = task
        self._prune()
        task.aio_task = asyncio.create_task(self._run(task))
        return task

    async def _run(self, task: Task):
        task.status = "running"
        task.started_at = time.time()
        async with self._sem:
            try:
                # 任务启动时重新读配置，并把任务级临时覆盖合并进 video_analysis
                config = config_store.load_config()
                if task.overrides:
                    va = dict(config.get("video_analysis", {}))
                    va.update(task.overrides)
                    config["video_analysis"] = va
                    task.logs.append(f"临时参数覆盖: {task.overrides}")

                emit = lambda t, d: self._emit(task, t, d)
                if task.mode == "download":
                    result = await run_download(task.url, config, emit)
                elif task.mode == "parse":
                    source = task.parse_source or task.url
                    result = await run_parse(task.source_type or "url", source, config, emit)
                else:
                    result = await run_pipeline(task.url, config, emit)
                task.result = result
                task.title = result.get("title", "")
            except PipelineError as e:
                task.error = str(e)
                self._emit(task, "error", {"message": str(e)})
            except Exception as e:
                detail = traceback.format_exc()
                task.error = f"内部错误: {e}"
                task.logs.append(detail)
                self._emit(task, "error", {"message": f"内部错误: {e}"})
            finally:
                if task.status != "completed":
                    task.status = "failed"
                task.finished_at = time.time()
                self._emit(task, "task_status", {"status": task.status})

    # ---------- 事件 ----------

    def _emit(self, task: Task, event_type: str, data: Dict[str, Any]):
        if event_type == "log":
            task.logs.append(data.get("text", ""))
            if len(task.logs) > MAX_LOGS:
                del task.logs[: len(task.logs) - MAX_LOGS]
        elif event_type == "stage":
            task.stage = data
            task.logs.append(f"—— {data.get('label', '')} ——")
        elif event_type == "download_progress":
            task.progress = data
        elif event_type == "analysis_delta":
            # 流式解析增量：reasoning=思考过程，content=正文（累加供快照/重连补发）
            data = data or {}
            for key in ("reasoning", "content"):
                piece = data.get(key)
                if piece:
                    task.analysis[key] = (task.analysis.get(key) or "") + piece
        elif event_type == "analysis_reset":
            # 空转中断后清空已流出的思考/正文，避免快照里留下垃圾
            data = data or {}
            for key in ("reasoning", "content"):
                if data.get(key):
                    task.analysis[key] = ""
        elif event_type == "done":
            task.title = data.get("title", "")
            task.result = data
            task.status = "completed"

        event = {"type": event_type, "data": data}
        for q in list(task.subscribers):
            q.put_nowait(event)

    # ---------- 订阅（WebSocket） ----------

    def subscribe(self, task_id: str) -> Optional[asyncio.Queue]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        q: asyncio.Queue = asyncio.Queue()
        task.subscribers.append(q)
        return q

    def unsubscribe(self, task_id: str, q: asyncio.Queue):
        task = self._tasks.get(task_id)
        if task and q in task.subscribers:
            task.subscribers.remove(q)

    # ---------- 清理 ----------

    def _prune(self):
        # 任务过多时，删除最早的已完成/失败任务
        finished = [t for t in self._tasks.values() if t.status in ("completed", "failed")]
        overflow = len(self._tasks) - MAX_TASKS_KEPT
        if overflow > 0 and finished:
            finished.sort(key=lambda t: t.created_at)
            for t in finished[:overflow]:
                self._tasks.pop(t.id, None)


# 模块级单例（单 worker 运行，足够）
manager = TaskManager()
