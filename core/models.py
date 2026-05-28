from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    EXTRACTING_FRAMES = "extracting_frames"
    CLASSIFYING = "classifying"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"


class LanguageEnum(str, Enum):
    ZH = "zh"
    EN = "en"
    JA = "ja"


class LLMProviderEnum(str, Enum):
    OPENAI = "openai"
    CLAUDE = "claude"


class DetailEnum(str, Enum):
    BRIEF = "brief"
    NORMAL = "normal"
    DETAILED = "detailed"


class ModeEnum(str, Enum):
    AUDIO = "audio"
    MULTIMODAL = "multimodal"


class SummarizeRequest(BaseModel):
    url: str = Field(max_length=2000)
    language: LanguageEnum = LanguageEnum.ZH
    llm_provider: LLMProviderEnum = LLMProviderEnum.OPENAI
    detail: DetailEnum = DetailEnum.NORMAL
    mode: ModeEnum = ModeEnum.MULTIMODAL


class TaskResponse(BaseModel):
    task_id: str
    status: TaskStatus


class TaskDetail(BaseModel):
    task_id: str
    url: str
    platform: str
    status: TaskStatus
    summary: Optional[str] = None
    transcript: Optional[str] = None
    created_at: datetime
    completed_at: Optional[datetime] = None
    metadata: Optional[dict] = None
    error: Optional[str] = None
    favorite: bool = False
    progress: int = 0


class TaskListItem(BaseModel):
    task_id: str
    url: str
    platform: str
    status: TaskStatus
    created_at: datetime
    metadata: Optional[dict] = None
    favorite: bool = False
    progress: int = 0


class TaskListResponse(BaseModel):
    tasks: list[TaskListItem]


class StorageInfo(BaseModel):
    db_size_bytes: int
    cache_size_bytes: int
    task_count: int


class StorageCleanupResult(BaseModel):
    deleted_files: int
    deleted_tasks: int
    freed_bytes: int


class BatchSummarizeRequest(BaseModel):
    urls: list[str] = Field(max_length=50)
    language: LanguageEnum = LanguageEnum.ZH
    llm_provider: LLMProviderEnum = LLMProviderEnum.OPENAI
    detail: DetailEnum = DetailEnum.NORMAL
    mode: ModeEnum = ModeEnum.MULTIMODAL


class BatchTaskItem(BaseModel):
    task_id: str
    url: str
    status: TaskStatus


class BatchSummarizeResponse(BaseModel):
    tasks: list[BatchTaskItem]
    skipped: list[str] = []


class FavoriteRequest(BaseModel):
    favorite: bool = True


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"


class GroupSummarizeRequest(BaseModel):
    urls: list[str] = Field(min_length=2, max_length=10)
    language: LanguageEnum = LanguageEnum.ZH
    llm_provider: LLMProviderEnum = LLMProviderEnum.OPENAI
    detail: DetailEnum = DetailEnum.NORMAL
    mode: ModeEnum = ModeEnum.MULTIMODAL


class GroupSummarizeResponse(BaseModel):
    group_id: str
    task_ids: list[str]
    skipped: list[str] = []


class GroupStatusResponse(BaseModel):
    group_id: str
    status: str  # pending / partial / complete / failed
    tasks: list[TaskListItem]
    synthesis: Optional[TaskListItem] = None
