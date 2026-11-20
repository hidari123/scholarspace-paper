"""导入服务测试。

⚠️ **重点验证「不会重复入库」** ——
   文献库最怕的就是重复数据。
"""

from __future__ import annotations

from dataclasses import replace

from paper_core.application.import_service import ImportService
from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import (
    DOI,
    ArxivId,
    AuthorId,
    PaperId,
    SourceType,
)
from paper_core.infrastructure.memory import InMemoryPaperRepository


def make_paper(
    title: str = "Deep Learning for Image Recognition",
    authors: tuple[str, ...] = ("John Smith",),
    year: int | None = 2024,
    **extra: object,
) -> Paper:
    """构造论文.

    ⚠️ **其余字段用 **extra** ——
    参数太多（ruff PLR0913 限制 5 个）。
    """
    source = extra.pop("source", SourceType.ARXIV)
    source_id = str(extra.pop("source_id", "2401.00001"))
    doi_value = extra.pop("doi", None)
    arxiv_value = extra.pop("arxiv_id", None)

    return Paper(
        paper_id=PaperId(f"{source.value}:{source_id}"),
        title=title,
        authors=tuple(
            Author(author_id=AuthorId(f"a{i}"), name=name) for i, name in enumerate(authors)
        ),
        year=year,
        doi=DOI(str(doi_value)) if doi_value else None,
        arxiv_id=ArxivId(str(arxiv_value)) if arxiv_value else None,
        source=source,
        source_id=source_id,
        **extra,  # type: ignore[arg-type]
    )


class TestImport:
    """导入."""

    async def test_imports_new_paper(self) -> None:
        """新论文入库。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        report = await service.import_papers((make_paper(),))

        assert report.inserted == 1
        assert report.updated == 0
        assert report.skipped == 0
        assert report.fetched == 1

    async def test_does_not_duplicate_same_paper(self) -> None:
        """⚠️ **同一篇不能入库两次**。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        paper = make_paper()
        await service.import_papers((paper,))
        report = await service.import_papers((paper,))

        assert report.inserted == 0
        assert len(await repository.list_all()) == 1

    async def test_merges_across_sources(self) -> None:
        """⚠️ **跨来源合并** —— arXiv 和 Crossref 的同一篇。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        arxiv = make_paper(arxiv_id="2401.00001")
        crossref = make_paper(
            source=SourceType.CROSSREF,
            source_id="cr-1",
            doi="10.1000/xyz",
            abstract="Abstract from Crossref.",
        )

        await service.import_papers((arxiv,))
        report = await service.import_papers((crossref,))

        assert report.updated == 1
        assert len(await repository.list_all()) == 1

        merged = await repository.get(arxiv.paper_id)
        assert merged is not None
        assert merged.abstract == "Abstract from Crossref."

    async def test_keeps_different_papers_separate(self) -> None:
        """⚠️ **不同论文不能被合并**。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        first = make_paper(title="Paper About Cats")
        second = make_paper(
            title="Paper About Dogs",
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        await service.import_papers((first, second))

        assert len(await repository.list_all()) == 2

    async def test_report_has_details(self) -> None:
        """⚠️ **必须有处理说明** —— 用户要知道发生了什么。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        report = await service.import_papers((make_paper(),))

        assert report.details
        assert "新增" in report.details[0]

    async def test_import_from_source(self) -> None:
        """⚠️ **从数据源导入**。"""
        repository = InMemoryPaperRepository()
        service = ImportService(repository)

        class FakeSource:
            """假数据源。"""

            source = SourceType.ARXIV

            async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
                """检索."""
                del query  # ⚠️ 显式标记未使用 —— 避免 ARG002
                return (make_paper(),)

        report = await service.import_from_source(FakeSource(), SearchQuery())

        assert report.inserted == 1


class TestSearch:
    """检索."""

    async def test_search_by_text(self) -> None:
        """自由文本检索。"""
        repository = InMemoryPaperRepository()
        await repository.save(make_paper(title="Neural Networks for Vision"))
        await repository.save(make_paper(title="Graph Theory Basics", source_id="2"))

        results = await repository.search(SearchQuery("neural"))

        assert len(results) == 1
        assert results[0].title == "Neural Networks for Vision"

    async def test_search_by_author(self) -> None:
        """按作者检索。"""
        repository = InMemoryPaperRepository()
        await repository.save(make_paper(authors=("John Smith",)))
        await repository.save(make_paper(authors=("Jane Doe",), source_id="2", title="Other Paper"))

        results = await repository.search(SearchQuery(author="smith"))

        assert len(results) == 1

    async def test_search_by_year_range(self) -> None:
        """按年份区间。"""
        repository = InMemoryPaperRepository()
        await repository.save(make_paper(year=2020, source_id="1"))
        await repository.save(make_paper(year=2024, source_id="2", title="Other"))

        results = await repository.search(SearchQuery(date_from=2023))

        assert len(results) == 1
        assert results[0].year == 2024

    async def test_search_sorted_by_citations(self) -> None:
        """⚠️ **按引用数降序** —— 最相关的排前面。"""
        repository = InMemoryPaperRepository()
        await repository.save(
            replace(make_paper(title="Less Cited", source_id="1"), citation_count=5)
        )
        await repository.save(
            replace(make_paper(title="More Cited", source_id="2"), citation_count=100)
        )

        results = await repository.search(SearchQuery())

        assert results[0].title == "More Cited"

    async def test_search_respects_limit(self) -> None:
        """⚠️ **限制返回条数** —— 防止一次拉太多。"""
        repository = InMemoryPaperRepository()
        for index in range(10):
            await repository.save(make_paper(title=f"Paper {index}", source_id=str(index)))

        results = await repository.search(SearchQuery(limit=3))

        assert len(results) == 3
