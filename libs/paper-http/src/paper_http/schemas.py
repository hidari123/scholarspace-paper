"""请求/响应模型 —— Pydantic v2。

⚠️ **领域层的 ID 是 `str`** ——
HTTP 边界上要转成 UUID。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "AuthorResponse",
    "DedupDecisionResponse",
    "ErrorResponse",
    "ImportReportResponse",
    "ImportRequest",
    "PaperResponse",
    "SearchRequest",
]


class _StrictModel(BaseModel):
    """严格模式的基类。"""

    model_config = ConfigDict(extra="forbid", from_attributes=True)


class ErrorResponse(BaseModel):
    """统一错误响应。"""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="错误码")
    message: str = Field(description="错误描述")


class AuthorResponse(_StrictModel):
    """作者响应。"""

    author_id: str
    name: str
    orcid: str = ""
    institutions: list[str] = Field(default_factory=list)


class PaperResponse(_StrictModel):
    """论文响应.."""

    paper_id: str
    title: str
    abstract: str = ""
    authors: list[AuthorResponse] = Field(default_factory=list)
    year: int | None = None
    publication_type: str = "unknown"
    open_access: str = "unknown"
    venue: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str | None = None
    arxiv_id: str | None = None
    publisher: str = ""
    citation_count: int = 0
    cited_by_count: int = 0
    keywords: list[str] = Field(default_factory=list)
    source: str = "manual"
    source_id: str = ""
    pdf_url: str = ""
    status: str = "imported"
    #: ⚠️ **全文体积大** —— 默认不返回
    has_full_text: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SearchRequest(_StrictModel):
    """检索请求."""

    #: 自由文本
    query: str = Field(default="", max_length=1000, description="自由文本")
    #: 作者名
    author: str = Field(default="", max_length=200, description="作者名")
    #: 期刊/会议
    venue: str = Field(default="", max_length=200, description="期刊或会议")
    #: 关键词
    keywords: list[str] = Field(default_factory=list, description="关键词")
    #: 起始年份
    date_from: int | None = Field(default=None, ge=1000, le=2100, description="起始年份")
    #: 结束年份
    date_to: int | None = Field(default=None, ge=1000, le=2100, description="结束年份")
    #: 只看开放获取
    open_access_only: bool = Field(default=False, description="只看开放获取")
    #: 返回条数
    limit: int = Field(default=20, ge=1, le=100, description="返回条数")
    #: 偏移
    offset: int = Field(default=0, ge=0, description="偏移")
    #: ⚠️ **要不要连外部源一起搜**
    include_external: bool = Field(default=False, description="连外部源一起搜")


class ImportRequest(_StrictModel):
    """导入请求."""

    #: 数据源
    source: str = Field(default="arxiv", description="数据源")
    #: 检索条件
    query: str = Field(default="", max_length=1000, description="检索条件")
    #: 条数上限
    limit: int = Field(default=20, ge=1, le=100, description="条数上限")


class DedupDecisionResponse(_StrictModel):
    """去重判定响应."""

    #: 是否是同一篇
    is_same: bool
    #: 判定依据
    reason: str
    #: 置信度（0~1）
    confidence: float = Field(ge=0.0, le=1.0)


class ImportReportResponse(_StrictModel):
    """导入报告响应."""

    #: 拉取到的总数
    fetched: int
    #: 新增
    inserted: int
    #: 更新（合并）
    updated: int
    #: 跳过
    skipped: int
    #: 每条的处理说明
    details: list[str] = Field(default_factory=list)
