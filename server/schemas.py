"""API 请求/响应模型"""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class TaskOverrides(BaseModel):
    """任务级临时参数覆盖（仅 video_analysis，白名单字段）"""
    fps: Optional[int] = Field(default=None, ge=1, le=30)
    media_resolution: Optional[str] = Field(default=None, pattern="^(default|max)$")
    prompt: Optional[str] = Field(default=None, min_length=1)


class TaskCreateRequest(BaseModel):
    url: str = Field(default="", description="抖音链接/口令，或 parse 模式下的视频直链")
    mode: Literal["full", "download", "parse"] = Field(default="full")
    source_type: Optional[Literal["url", "file"]] = Field(default=None, description="parse 模式输入类型")
    upload_id: Optional[str] = Field(default=None, description="parse+file 模式的上传ID")
    overrides: Optional[TaskOverrides] = None


class TaskView(BaseModel):
    id: str
    url: str
    mode: str = "full"  # full / download / parse
    source_type: Optional[str] = None
    status: str  # pending / running / completed / failed
    title: str = ""
    error: Optional[str] = None
    created_at: float = 0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    stage: Optional[Dict[str, Any]] = None
    progress: Optional[Dict[str, Any]] = None


class TaskDetailView(TaskView):
    logs: List[str] = Field(default_factory=list)
    result: Optional[Dict[str, Any]] = None


class HistoryFile(BaseModel):
    name: str
    size: int
    mtime: float


class HistoryItem(BaseModel):
    name: str
    mtime: float
    files: List[HistoryFile] = Field(default_factory=list)


class ConfigBody(BaseModel):
    config: Dict[str, Any]
