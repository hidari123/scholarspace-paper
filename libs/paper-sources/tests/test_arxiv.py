"""arXiv 适配器测试。

⚠️ **用假的 Atom XML** —— 不打真实网络（测试要能离线跑）。
"""

from __future__ import annotations

import httpx
from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Paper
from paper_core.domain.value_objects import (
    PaperId,
    PublicationType,
    SourceType,
)

from paper_sources.arxiv import ArxivSource

#: 一条真实的 arXiv Atom 响应（简化）
ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-02T18:00:00Z</published>
    <title>Deep Residual Learning for Image Recognition</title>
    <summary>  We present a deep residual learning framework.
    It surpasses the state of the art.  </summary>
    <author><name>Kaiming He</name></author>
    <author><name>Zhang Xiangyu</name></author>
    <link href="http://arxiv.org/abs/2401.00001v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.00001v1" rel="related" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/hep-th/9901001v2</id>
    <published>1999-01-01T00:00:00Z</published>
    <title>A Very Old Paper</title>
    <summary>An old paper.</summary>
    <author><name>Somebody</name></author>
  </entry>
</feed>
"""

#: ⚠️ **空 feed** —— 模拟查不到
EMPTY_ATOM = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"></feed>
"""


def make_client(body: str, status_code: int = 200) -> httpx.AsyncClient:
    """造一个返回固定内容的客户端."""

    def handler(_request: httpx.Request) -> httpx.Response:
        """固定响应。"""
        return httpx.Response(status_code, text=body)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestArxivParsing:
    """Atom 解析."""

    async def test_parses_entries(self) -> None:
        """⚠️ **能解析出论文**。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery("deep learning"))

        assert len(papers) == 2

    async def test_parses_title(self) -> None:
        """标题。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].title == "Deep Residual Learning for Image Recognition"

    async def test_parses_authors(self) -> None:
        """⚠️ **多个作者**。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert len(papers[0].authors) == 2
        assert papers[0].authors[0].name == "Kaiming He"

    async def test_parses_year(self) -> None:
        """年份从 published 抽。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].year == 2024
        assert papers[1].year == 1999

    async def test_normalizes_abstract_whitespace(self) -> None:
        """⚠️ **摘要的空白要规整** —— XML 里的换行会保留。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert "\n" not in papers[0].abstract
        assert papers[0].abstract.startswith("We present")

    async def test_extracts_pdf_url(self) -> None:
        """⚠️ **要选 `application/pdf` 那个链接**。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].pdf_url == "http://arxiv.org/pdf/2401.00001v1"

    async def test_strips_version_suffix(self) -> None:
        """⚠️ **版本号要去掉** —— `2401.00001v1` 和 `2401.00001` 是同一篇。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].arxiv_id == "2401.00001"

    async def test_handles_old_style_id(self) -> None:
        """⚠️ **旧式 arXiv ID** —— `hep-th/9901001`（带斜杠）。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[1].arxiv_id == "hep-th/9901001"

    async def test_source_type(self) -> None:
        """来源类型。"""
        async with make_client(ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers[0].source is SourceType.ARXIV

    async def test_empty_feed(self) -> None:
        """空结果。"""
        async with make_client(EMPTY_ATOM) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()


class TestArxivRobustness:
    """健壮性."""

    async def test_malformed_xml_returns_empty(self) -> None:
        """⚠️ **XML 坏了不能崩** —— 返回空列表。"""
        async with make_client("not xml at all") as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()

    async def test_entry_without_title_is_skipped(self) -> None:
        """⚠️ **没标题的条目要跳过** —— 不能产生空标题的论文。"""
        broken = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <published>2024-01-02T18:00:00Z</published>
  </entry>
</feed>
"""
        async with make_client(broken) as client:
            source = ArxivSource(client)
            papers = await source.search(SearchQuery())

        assert papers == ()

    async def test_fetch_returns_none_when_empty(self) -> None:
        """⚠️ **取不到返回 None** —— 不能抛异常。"""
        async with make_client(EMPTY_ATOM) as client:
            source = ArxivSource(client)
            paper = await source.fetch("2401.00001")

        assert paper is None


class TestArxivQuery:
    """查询参数."""

    async def test_uses_arxiv_search_syntax(self) -> None:
        """⚠️ **arXiv 的检索语法** —— `ti:` / `au:` / `all:`。"""
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, text=EMPTY_ATOM)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = ArxivSource(client)
            await source.search(SearchQuery("transformers", author="Vaswani"))

        assert captured["search_query"] == "all:transformers AND au:Vaswani"

    async def test_respects_limit(self) -> None:
        """⚠️ **限制条数** —— 不能一次拉 10000 条。"""
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, text=EMPTY_ATOM)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = ArxivSource(client)
            await source.search(SearchQuery(limit=25))

        assert captured["max_results"] == "25"

    async def test_caps_limit_at_100(self) -> None:
        """⚠️ **上限 100** —— arXiv API 的限制。"""
        captured: dict[str, object] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, text=EMPTY_ATOM)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            source = ArxivSource(client)
            await source.search(SearchQuery(limit=5000))

        assert captured["max_results"] == "100"

    async def test_sends_user_agent(self) -> None:
        """⚠️ **必须带 User-Agent** —— arXiv 会封禁没有 UA 的请求。

        ⚠️ **注入的客户端用调用方自己的 UA** ——
        这里测的是「自己建客户端」时有没有带上。
        """
        source = ArxivSource()

        client = await source._ensure_client().__aenter__()
        try:
            user_agent = client.headers.get("User-Agent", "")
        finally:
            await client.aclose()

        assert "scholarspace" in user_agent


class TestArxivTypes:
    """类型."""

    def test_publication_type_defaults_to_unknown(self) -> None:
        """⚠️ **arXiv 不提供出版类型** —— 未知。"""
        paper = Paper(paper_id=PaperId("arxiv:x"), title="T")

        assert paper.publication_type is PublicationType.UNKNOWN
