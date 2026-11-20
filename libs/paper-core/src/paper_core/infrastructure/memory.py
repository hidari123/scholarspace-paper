"""内存实现 —— 开发与测试用。"""

from __future__ import annotations

import asyncio

from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import PaperId

__all__ = ["InMemoryAuthorRepository", "InMemoryPaperRepository"]


class InMemoryPaperRepository:
    """内存论文仓储."""

    def __init__(self) -> None:
        self._papers: dict[PaperId, Paper] = {}
        self._lock = asyncio.Lock()

    async def save(self, paper: Paper) -> Paper:
        """保存论文。"""
        async with self._lock:
            self._papers[paper.paper_id] = paper

        return paper

    async def get(self, paper_id: PaperId) -> Paper | None:
        """取论文。"""
        return self._papers.get(paper_id)

    async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
        """检索。

        ⚠️ **这里是最简单的实现** ——
        真实实现靠数据库的全文索引。
        """
        matched = [paper for paper in self._papers.values() if self._matches(paper, query)]

        # ⚠️ **按引用数降序** —— 检索结果里最相关的排前面
        matched.sort(key=lambda paper: paper.citation_count, reverse=True)

        start = query.offset
        end = start + query.limit

        return tuple(matched[start:end])

    async def list_all(self) -> tuple[Paper, ...]:
        """全部论文."""
        return tuple(self._papers.values())

    async def find_by_canonical_key(self, key: str) -> Paper | None:
        """按去重键查找。"""
        for paper in self._papers.values():
            if paper.canonical_key() == key:
                return paper

        return None

    async def delete(self, paper_id: PaperId) -> bool:
        """删除论文。"""
        async with self._lock:
            return self._papers.pop(paper_id, None) is not None

    def _matches(self, paper: Paper, query: SearchQuery) -> bool:
        """是否匹配检索条件.

        ⚠️ **拆成两个方法** ——
        返回语句太多（ruff PLR0911 限制 6 个），
        而且「硬过滤」和「软过滤」本来就是两类。
        """
        if not self._matches_filters(paper, query):
            return False

        return self._matches_terms(paper, query)

    def _matches_filters(self, paper: Paper, query: SearchQuery) -> bool:
        """硬过滤 —— 不满足就直接排除。"""
        if query.open_access_only and not paper.is_open_access():
            return False

        if query.date_from is not None and (paper.year is None or paper.year < query.date_from):
            return False

        return not (
            query.date_to is not None and (paper.year is None or paper.year > query.date_to)
        )

    def _matches_terms(self, paper: Paper, query: SearchQuery) -> bool:
        """软过滤 —— 关键词类的匹配。"""
        if query.venue and query.venue.lower() not in paper.venue.lower():
            return False

        if query.author:
            author_query = query.author.lower()
            if not any(author_query in name.lower() for name in paper.author_names()):
                return False

        if query.keywords:
            paper_keywords = {keyword.lower() for keyword in paper.keywords}
            if not paper_keywords.intersection(keyword.lower() for keyword in query.keywords):
                return False

        if query.query:
            text_query = query.query.lower()
            haystack = f"{paper.title} {paper.abstract}".lower()
            if text_query not in haystack:
                return False

        return True


class InMemoryAuthorRepository:
    """内存作者仓储."""

    def __init__(self) -> None:
        self._authors: dict[str, Author] = {}
        self._lock = asyncio.Lock()

    async def save(self, author: Author) -> Author:
        """保存作者。"""
        async with self._lock:
            self._authors[author.author_id] = author

        return author

    async def get(self, author_id: str) -> Author | None:
        """取作者。"""
        return self._authors.get(author_id)
