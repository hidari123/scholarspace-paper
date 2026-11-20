"""应用层端口 —— 存储与外部数据源的契约。

⚠️ **端口在应用层，实现在基础设施层** ——
   换数据源、加数据源都不影响领域层。

⚠️ **数据源是「异步」** —— 网络请求不能阻塞事件循环。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import PaperId, SourceType

__all__ = [
    "AuthorRepositoryPort",
    "PaperRepositoryPort",
    "PaperSourcePort",
    "SearchQuery",
]


@dataclass(frozen=True, slots=True)
class SearchQuery:
    """检索条件.

    ⚠️ **所有字段都是可选的** —— 空的条件 = 列出全部。

    ⚠️ **用 dataclass 而不是手写 __init__** ——
    参数太多（ruff PLR0913 限制 5 个），
    dataclass 的字段不会触发这个规则。
    """

    #: 自由文本
    query: str = ""
    #: 作者名
    author: str = ""
    #: 期刊/会议
    venue: str = ""
    #: 关键词
    keywords: tuple[str, ...] = ()
    #: 起始年份
    date_from: int | None = None
    #: 结束年份
    date_to: int | None = None
    #: 只看开放获取
    open_access_only: bool = False
    #: 返回条数
    limit: int = 20
    #: 偏移
    offset: int = 0


@runtime_checkable
class PaperRepositoryPort(Protocol):
    """论文仓储端口."""

    async def save(self, paper: Paper) -> Paper:
        """保存论文。"""
        ...

    async def get(self, paper_id: PaperId) -> Paper | None:
        """取论文。

        :return: None 表示不存在
        """
        ...

    async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
        """检索。"""
        ...

    async def list_all(self) -> tuple[Paper, ...]:
        """全部论文.

        ⚠️ **模糊去重要遍历全库** ——
        真实实现应该配合数据库索引，
        但端口必须能支持。
        """
        ...

    async def find_by_canonical_key(self, key: str) -> Paper | None:
        """按去重键查找。

        ⚠️ **跨来源去重靠它** ——
        同一篇论文可能同时在 arXiv 和 Crossref 里有记录。
        """
        ...

    async def delete(self, paper_id: PaperId) -> bool:
        """删除论文。"""
        ...


@runtime_checkable
class AuthorRepositoryPort(Protocol):
    """作者仓储端口."""

    async def save(self, author: Author) -> Author:
        """保存作者。"""
        ...

    async def get(self, author_id: str) -> Author | None:
        """取作者。"""
        ...


@runtime_checkable
class PaperSourcePort(Protocol):
    """外部数据源端口.

    ⚠️ **每个数据源一个实现** ——
    arXiv、Crossref、Semantic Scholar 各一个。
    全部实现同一个协议 → 上层代码不用区分。
    """

    #: 数据源类型
    source: SourceType

    async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
        """检索。"""
        ...

    async def fetch(self, source_id: str) -> Paper | None:
        """按来源主键取单篇。"""
        ...
