"""解析任务 API"""

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from ..schemas import TaskCreateRequest, TaskView, TaskDetailView
from ..task_manager import manager
from .uploads import resolve_upload

router = APIRouter(prefix="/api", tags=["tasks"])


@router.post("/tasks", response_model=TaskView)
async def create_task(req: TaskCreateRequest):
    overrides = req.overrides.model_dump(exclude_none=True) if req.overrides else None

    if req.mode in ("full", "download"):
        if not req.url.strip():
            raise HTTPException(status_code=400, detail="请提供抖音链接或口令")
        task = manager.create(req.url, mode=req.mode, overrides=overrides)
        return manager.view(task)

    # parse 模式
    if req.source_type == "url":
        if not req.url.strip():
            raise HTTPException(status_code=400, detail="请提供视频直链")
        task = manager.create(req.url, mode="parse", source_type="url",
                              parse_source=req.url.strip(), overrides=overrides)
        return manager.view(task)

    if req.source_type == "file":
        if not req.upload_id:
            raise HTTPException(status_code=400, detail="缺少上传文件")
        path = resolve_upload(req.upload_id)
        if not path:
            raise HTTPException(status_code=404, detail="上传文件不存在或已失效，请重新上传")
        task = manager.create(path.name, mode="parse", source_type="file",
                              parse_source=str(path), overrides=overrides)
        return manager.view(task)

    raise HTTPException(status_code=400, detail="parse 模式必须指定 source_type（url/file）")


@router.get("/tasks", response_model=list[TaskView])
def list_tasks():
    return [manager.view(t) for t in manager.list_all()]


@router.get("/tasks/{task_id}", response_model=TaskDetailView)
def get_task(task_id: str):
    task = manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return manager.view(task, detail=True)


@router.websocket("/ws/tasks/{task_id}")
async def task_ws(ws: WebSocket, task_id: str):
    task = manager.get(task_id)
    if not task:
        await ws.close(code=4404)
        return

    await ws.accept()
    queue = manager.subscribe(task_id)
    try:
        # 先发当前快照（含日志/阶段/最新进度/结果），支持断线重连补发
        await ws.send_json({"type": "snapshot", "data": manager.view(task, detail=True)})

        if task.status in ("completed", "failed"):
            await ws.close()
            return

        while True:
            event = await queue.get()
            await ws.send_json(event)
            if event["type"] in ("task_status",):
                await ws.close()
                return
    except WebSocketDisconnect:
        pass
    finally:
        if queue is not None:
            manager.unsubscribe(task_id, queue)
