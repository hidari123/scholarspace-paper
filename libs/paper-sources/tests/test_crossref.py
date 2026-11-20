"""Crossref 适配器测试。

⚠️ **用假的 JSON** —— 不打真实网络。
"""

from __future__ import annotations

import httpx
from paper_core.application.ports import SearchQuery
from paper_core.domain.value_objects import OpenAccessStatus, PublicationType, SourceType

from paper_sources.crossref import CrossrefSource

#: 一条真实的 Crossref 响应（简化）
CROSSREF = {
    "message": {
        "items": [
            {
                "DOI": "10.1000/xyz123",
                "type": "journal-article",
                "title": ["Attention Is All You Need"],
                "abstract": (
                    "<jats:p>We propose the Transformer, a new simple network "
                    "architecture based solely on attention mechanisms.</jats:p>"
                ),
                "container-title": ["Advances in Neural Information Processing Systems"],
                "volume": "30",
                "issue": "1",
                "page": "5998-6008",
                "publisher": "Curran Associates, Inc.",
                "issued": {"date-parts": [[2017, 6, 12]]},
                "author": [
                    {
                        "given": "Ashish",
                        "family": "Vaswani",
                        "ORCID": "0000-0002-1825-0097",
                        "affiliation": [{"name": "Google Brain"}],
                    },
                    {"given": "Noam", "family": "Shazeer"},
                ],
                "license": [{"URL": "https://creativecommons.org/licenses/by/4.0/"}],
                "indexed": {"date-time": "2024-01-15T10:00:00Z"},
            },
            {
                "DOI": "10.1000/proc2024",
                "type": "proceedings-article",
                "title": ["A Conference Paper"],
                "issued": {"date-parts": [[2024]]},
                "author": [{"name": "Someone Smith"}],
            },
        ]
    }
}


def make_client(payload: object, status_code: int = 200) -> httpx.AsyncClient:
    """造一个返回固定 JSON 的客户端。"""

    def handler(_request: httpx.Request) -> httpx.Response:
        """固定响应。"""
        return httpx.Response(status_code, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestCrossrefParsing:
    """解析."""

    async def test_parses_items(self) -> None:
        """能解析出论文。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery("transformer"))

        assert len(papers) == 2

    async def test_parses_title(self) -> None:
        """标题。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].title == "Attention Is All You Need"

    async def test_parses_doi_lowercase(self) -> None:
        """⚠️ **DOI 要转小写** —— 大小写不敏感，统一存。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].doi == "10.1000/xyz123"

    async def test_strips_jats_tags_from_abstract(self) -> None:
        """⚠️ **摘要的 XML 标签要剥掉**。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert "<" not in papers[0].abstract
        assert papers[0].abstract.startswith("We propose")

    async def test_parses_authors(self) -> None:
        """作者。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert len(papers[0].authors) == 2
        assert papers[0].authors[0].name == "Ashish Vaswani"

    async def test_parses_orcid(self) -> None:
        """ORCID。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].authors[0].orcid == "0000-0002-1825-0097"

    async def test_parses_affiliation(self) -> None:
        """机构。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].authors[0].institutions[0].name == "Google Brain"

    async def test_extracts_year(self) -> None:
        """年份。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].year == 2017
        assert papers[1].year == 2024

    async def test_maps_publication_type(self) -> None:
        """⚠️ **类型映射**。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].publication_type is PublicationType.JOURNAL_ARTICLE
        assert papers[1].publication_type is PublicationType.CONFERENCE_PAPER

    async def test_detects_open_access(self) -> None:
        """⚠️ **CC 许可 → 开放获取**。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].open_access is OpenAccessStatus.OPEN

    async def test_source_type(self) -> None:
        """来源类型。"""
        async with make_client(CROSSREF) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].source is SourceType.CROSSREF


class TestCrossrefQuery:
    """查询参数."""

    async def test_uses_crossref_parameter_names(self) -> None:
        """⚠️ **Crossref 的参数名跟 arXiv 完全不同**。"""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=CROSSREF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefSource(client)
            await source.search(SearchQuery("transformer", author="Vaswani"))

        assert captured["query.bibliographic"] == "transformer"
        assert captured["query.author"] == "Vaswani"

    async def test_uses_filter_for_dates(self) -> None:
        """⚠️ **日期过滤用 `filter`** —— 不是独立参数。"""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=CROSSREF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefSource(client)
            await source.search(SearchQuery(date_from=2020, date_to=2024))

        assert "from-pub-date:2020-01-01" in captured["filter"]
        assert "until-pub-date:2024-12-31" in captured["filter"]

    async def test_sends_mailto(self) -> None:
        """⚠️ **必须带 mailto** —— 进 Crossref 的礼貌池。"""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=CROSSREF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefSource(client, mailto="test@example.org")
            await source.search(SearchQuery())

        assert captured["mailto"] == "test@example.org"

    async def test_open_access_filter(self) -> None:
        """开放获取过滤。"""
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json=CROSSREF)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = CrossrefSource(client)
            await source.search(SearchQuery(open_access_only=True))

        assert "has-license:true" in captured["filter"]


class TestCrossrefRobustness:
    """健壮性."""

    async def test_missing_doi_is_skipped(self) -> None:
        """⚠️ **没 DOI 的要跳过**。"""
        payload = {"message": {"items": [{"title": ["No DOI Here"]}]}}

        async with make_client(payload) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()

    async def test_missing_title_is_skipped(self) -> None:
        """⚠️ **没标题的要跳过**。"""
        payload = {"message": {"items": [{"DOI": "10.1000/x"}]}}

        async with make_client(payload) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()

    async def test_empty_response(self) -> None:
        """空响应。"""
        async with make_client({"message": {"items": []}}) as client:
            source = CrossrefSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()

    async def test_fetch_returns_none_on_404(self) -> None:
        """⚠️ **404 → None** —— 不能抛异常。"""
        async with make_client({}, status_code=404) as client:
            source = CrossrefSource(client)
            paper = await source.fetch("10.1000/missing")

        assert paper is None
