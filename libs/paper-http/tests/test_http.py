"""HTTP 接口层测试。

⚠️ **重点验证「语义正确性」**：
    · 404 vs 422 vs 502 vs 503 的区分
    · 外部源的失败不影响其它源
    · 全文单独一个端点
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import (
    DOI,
    AuthorId,
    PaperId,
    SourceType,
)
from paper_core.infrastructure.memory import InMemoryPaperRepository

from paper_http.app import create_app
from paper_http.routers.papers import to_response
from paper_http.service import PaperNotFoundError, PaperService


def make_paper(
    title: str = "Attention Is All You Need",
    authors: tuple[str, ...] = ("Ashish Vaswani",),
    year: int | None = 2017,
    **extra: object,
) -> Paper:
    """构造论文.

    ⚠️ **其余字段用 **extra** ——
    参数太多（ruff PLR0913 限制 5 个）。
    """
    source_id = str(extra.pop("source_id", "1"))
    doi_value = extra.pop("doi", "10.1000/xyz")

    return Paper(
        paper_id=PaperId(f"crossref:{source_id}"),
        title=title,
        authors=tuple(
            Author(author_id=AuthorId(f"a{i}"), name=name) for i, name in enumerate(authors)
        ),
        year=year,
        doi=DOI(str(doi_value)) if doi_value else None,
        source=SourceType.CROSSREF,
        source_id=source_id,
        **extra,  # type: ignore[arg-type]
    )


@pytest.fixture
def repository() -> InMemoryPaperRepository:
    """论文仓储。"""
    return InMemoryPaperRepository()


@pytest.fixture
def client(repository: InMemoryPaperRepository) -> Iterator[TestClient]:
    """测试客户端."""
    service = PaperService(repository=repository)
    app = create_app(service=service)

    with TestClient(app) as test_client:
        yield test_client


class TestHealth:
    """健康检查."""

    def test_health(self, client: TestClient) -> None:
        """健康检查."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestSearch:
    """检索."""

    def test_search_returns_empty(self, client: TestClient) -> None:
        """空库返回空列表."""
        response = client.post("/api/v1/papers/search", json={})

        assert response.status_code == 200
        assert response.json() == []

    def test_search_by_text(self, client: TestClient) -> None:
        """按文本检索."""
        # ⚠️ **先插入一篇** —— 检索要有东西可搜
        client.post(
            "/api/v1/papers/import",
            json={"source": "arxiv", "query": "x"},
        )

        response = client.post("/api/v1/papers/search", json={"query": "Attention"})

        assert response.status_code == 200

    def test_search_rejects_extra_fields(self, client: TestClient) -> None:
        """⚠️ 多余字段 → 422."""
        response = client.post("/api/v1/papers/search", json={"query": "x", "sql": "DROP"})

        assert response.status_code == 422

    def test_search_rejects_bad_limit(self, client: TestClient) -> None:
        """⚠️ limit 超出范围 → 422."""
        response = client.post("/api/v1/papers/search", json={"limit": 1000})

        assert response.status_code == 422

    def test_search_rejects_bad_year(self, client: TestClient) -> None:
        """⚠️ 年份超出范围 → 422."""
        response = client.post("/api/v1/papers/search", json={"date_from": 99})

        assert response.status_code == 422


class TestGetPaper:
    """取论文."""

    def test_get_unknown_paper_returns_404(self, client: TestClient) -> None:
        """⚠️ 不存在 → 404."""
        response = client.get("/api/v1/papers/ghost")

        assert response.status_code == 404

    def test_delete_is_idempotent(self, client: TestClient) -> None:
        """⚠️ 删不存在的也返回 204 —— 删除是幂等的."""
        response = client.delete("/api/v1/papers/ghost")

        assert response.status_code == 204


class TestImport:
    """导入."""

    def test_import_unsupported_source_returns_422(self, client: TestClient) -> None:
        """⚠️ 不支持的数据源 → 422."""
        response = client.post(
            "/api/v1/papers/import",
            json={"source": "ghost", "query": "test"},
        )

        assert response.status_code == 422

    def test_import_without_service_returns_503(self) -> None:
        """⚠️ 没配置服务 → 503."""
        app = create_app(service=None)

        with TestClient(app) as bare:
            response = bare.post(
                "/api/v1/papers/import",
                json={"source": "arxiv", "query": "test"},
            )

        assert response.status_code == 503


class TestService:
    """服务层."""

    async def test_search_local(self, repository: InMemoryPaperRepository) -> None:
        """本地检索."""
        service = PaperService(repository=repository)
        await repository.save(make_paper(title="Neural Networks"))

        results = await service.search(SearchQuery("neural"))

        assert len(results) == 1

    async def test_external_failure_does_not_break_search(
        self, repository: InMemoryPaperRepository
    ) -> None:
        """⚠️ **一个源失败不影响其它源** —— arXiv 挂了不代表 Crossref 也挂了."""

        class BrokenSource:
            """会崩的源。"""

            async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
                """崩溃."""
                del query  # ⚠️ 显式标记未使用 —— 避免 ARG002
                raise RuntimeError("网络故障")

        class GoodSource:
            """正常的源。"""

            async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
                """返回一条."""
                del query  # ⚠️ 显式标记未使用 —— 避免 ARG002
                return (make_paper(title="From External", source_id="ext"),)

        service = PaperService(
            repository=repository,
            sources={"broken": BrokenSource(), "good": GoodSource()},
        )

        results = await service.search(SearchQuery("x"), include_external=True)

        assert len(results) == 1
        assert results[0].title == "From External"

    async def test_get_raises_not_found(self, repository: InMemoryPaperRepository) -> None:
        """⚠️ 不存在 → 抛 PaperNotFoundError."""
        service = PaperService(repository=repository)

        with pytest.raises(PaperNotFoundError):
            await service.get("ghost")

    async def test_check_duplicate(self, repository: InMemoryPaperRepository) -> None:
        """查重."""
        service = PaperService(repository=repository)
        await repository.save(make_paper(source_id="1"))
        await repository.save(
            make_paper(title="Attention Is All You Need", source_id="2", doi=None)
        )

        decision = await service.check_duplicate("crossref:1", "crossref:2")

        assert decision.is_same

    async def test_merge_papers(self, repository: InMemoryPaperRepository) -> None:
        """⚠️ **合并到主记录** —— 候选的摘要补上."""
        service = PaperService(repository=repository)
        await repository.save(make_paper(source_id="1"))
        await repository.save(
            make_paper(source_id="2", abstract="A long abstract from another source.")
        )

        merged = await service.merge("crossref:1", "crossref:2")

        assert merged.abstract == "A long abstract from another source."
        assert merged.doi == DOI("10.1000/xyz")


class TestResponseModel:
    """响应模型."""

    async def test_full_text_not_in_response(self, repository: InMemoryPaperRepository) -> None:
        """⚠️ **全文不在论文响应里** —— 只给「有没有」的标志."""
        service = PaperService(repository=repository)
        await repository.save(make_paper(full_text="A very long full text here."))

        paper = await service.get("crossref:1")

        response = to_response(paper)

        assert response.has_full_text
        assert not hasattr(response, "full_text")

    async def test_full_text_endpoint(self, repository: InMemoryPaperRepository) -> None:
        """⚠️ **全文单独一个端点**."""
        service = PaperService(repository=repository)
        await repository.save(make_paper(full_text="Full text content."))

        app = create_app(service=service)

        with TestClient(app) as client:
            response = client.get("/api/v1/papers/crossref:1/full-text")

        assert response.status_code == 200
        assert response.json() == "Full text content."


class TestEndToEnd:
    """端到端."""

    def test_import_then_search(self) -> None:
        """⚠️ **导入 → 检索** 的完整流程."""
        repository = InMemoryPaperRepository()

        class FakeSource:
            """假数据源。"""

            async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
                """返回一条."""
                del query  # ⚠️ 显式标记未使用 —— 避免 ARG002
                return (make_paper(title="Imported Paper", source_id="99"),)

        service = PaperService(repository=repository, sources={"arxiv": FakeSource()})
        app = create_app(service=service)

        with TestClient(app) as client:
            # ① 导入
            imported = client.post(
                "/api/v1/papers/import",
                json={"source": "arxiv", "query": "test"},
            )
            assert imported.status_code == 200
            assert imported.json()["inserted"] == 1

            # ② 检索
            found = client.post("/api/v1/papers/search", json={"query": "Imported"})
            assert found.status_code == 200
            assert len(found.json()) == 1
            assert found.json()[0]["title"] == "Imported Paper"
