"""Crossref 适配器 —— REST JSON API。

⚠️ **Crossref 覆盖面最广** —— 期刊、会议、图书都有。

⚠️ **必须带 mailto** ——
Crossref 的「礼貌池」（polite pool）会优先处理带邮箱的请求，
响应更快更稳定。

⚠️ **日期是「区间」** ——
`published-print` 的 date-parts 可能是 `[[2024, 3]]`（只有年月）
或 `[[2024, 3, 15]]`（有日），
也可能有多组（印刷版 + 在线版）—— **取最早的那个**。
"""

from __future__ import annotations

import re
from typing import Any

import httpx
from paper_core.application.ports import PaperSourcePort, SearchQuery
from paper_core.domain.entities import Author, Institution, Paper
from paper_core.domain.value_objects import (
    DOI,
    AuthorId,
    OpenAccessStatus,
    PaperId,
    PublicationType,
    SourceType,
)

from paper_sources.arxiv import _BorrowedClient

__all__ = ["CrossrefSource"]

#: ⚠️ **JATS 标签** —— Crossref 的摘要有 XML 标签
_TAG_PATTERN = re.compile(r"<[^>]+>")

#: ⚠️ **HTTP 404** —— 取单篇时找不到
HTTP_NOT_FOUND = 404

#: Crossref API 端点
_CROSSREF_API = "https://api.crossref.org/works"

#: ⚠️ **User-Agent** —— Crossref 建议带上
_USER_AGENT = "scholarspace-paper/0.1 (mailto:scholarspace@example.com)"

#: ⚠️ **Crossref 的类型 → 我们的类型**
_TYPE_MAP = {
    "journal-article": PublicationType.JOURNAL_ARTICLE,
    "proceedings-article": PublicationType.CONFERENCE_PAPER,
    "posted-content": PublicationType.PREPRINT,
    "dissertation": PublicationType.THESIS,
    "book": PublicationType.BOOK,
    "report": PublicationType.REPORT,
    "reference-entry": PublicationType.UNKNOWN,
}


class CrossrefSource(PaperSourcePort):
    """Crossref 数据源."""

    #: 数据源类型
    source = SourceType.CROSSREF

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        mailto: str = "scholarspace@example.com",
    ) -> None:
        """初始化.

        :param client: HTTP 客户端（注入以便测试）
        :param mailto: 联系邮箱（进礼貌池）
        """
        self._client = client
        self._mailto = mailto
        self._owns_client = client is None

    async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
        """检索.

        :param query: 检索条件
        :return: 论文列表
        """
        params = self._build_params(query)

        async with self._ensure_client() as client:
            response = await client.get(_CROSSREF_API, params=params)
            response.raise_for_status()

        payload = response.json()
        items = payload.get("message", {}).get("items", [])

        # ⚠️ **解析失败的条目要跳过** ——
        # `_parse_item` 在缺 DOI / 缺标题时返回 None。
        papers: list[Paper] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            parsed = self._parse_item(item)
            if parsed is not None:
                papers.append(parsed)

        return tuple(papers)

    async def fetch(self, source_id: str) -> Paper | None:
        """按 DOI 取单篇.

        :param source_id: DOI
        :return: 论文；找不到返回 None
        """
        async with self._ensure_client() as client:
            response = await client.get(f"{_CROSSREF_API}/{source_id}")
            if response.status_code == HTTP_NOT_FOUND:
                return None
            response.raise_for_status()

        payload = response.json()
        item = payload.get("message")
        if not item:
            return None

        return self._parse_item(item)

    def _ensure_client(self) -> Any:
        """确保有 HTTP 客户端。"""
        if self._client is not None:
            return _BorrowedClient(self._client)

        return httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    def _build_params(self, query: SearchQuery) -> dict[str, str | int]:
        """构造查询参数.

        ⚠️ **Crossref 的参数名跟 arXiv 完全不同** ——
        `query.bibliographic` / `query.author` / `filter=from-pub-date:...`
        """
        params: dict[str, str | int] = {
            "rows": min(query.limit, 100),
            "offset": query.offset,
            "mailto": self._mailto,
        }

        if query.query:
            params["query.bibliographic"] = query.query
        if query.author:
            params["query.author"] = query.author
        if query.venue:
            params["query.container-title"] = query.venue

        # ⚠️ **日期过滤用 filter** —— 格式是 `from-pub-date:2024-01-01`
        filters: list[str] = []
        if query.date_from is not None:
            filters.append(f"from-pub-date:{query.date_from}-01-01")
        if query.date_to is not None:
            filters.append(f"until-pub-date:{query.date_to}-12-31")
        if query.open_access_only:
            filters.append("has-license:true")
        if filters:
            params["filter"] = ",".join(filters)

        return params

    def _parse_item(self, item: dict[str, Any]) -> Paper | None:
        """解析一条记录."""
        doi = item.get("DOI")
        if not doi:
            return None

        title_list = item.get("title") or []
        title = title_list[0] if title_list else ""
        if not title:
            return None

        authors = self._parse_authors(item.get("author") or [])
        year = self._extract_year(item)

        return Paper(
            paper_id=PaperId(f"crossref:{doi}"),
            title=title,
            abstract=self._extract_abstract(item),
            authors=authors,
            year=year,
            doi=DOI(doi.lower()),
            venue=self._extract_venue(item),
            volume=str(item.get("volume", "")),
            issue=str(item.get("issue", "")),
            pages=str(item.get("page", "")),
            publisher=str(item.get("publisher", "")),
            publication_type=self._map_type(str(item.get("type", ""))),
            open_access=self._extract_oa(item),
            source=SourceType.CROSSREF,
            source_id=doi,
            updated_at=str(item.get("indexed", {}).get("date-time", "")),
        )

    def _parse_authors(self, raw_authors: list[dict[str, Any]]) -> tuple[Author, ...]:
        """解析作者列表."""
        authors: list[Author] = []

        for index, raw in enumerate(raw_authors):
            name = raw.get("name") or self._compose_name(raw)
            if not name:
                continue

            institutions = tuple(
                Institution(
                    institution_id=str(raw.get("ORCID", "")),
                    name=aff.get("name", ""),
                )
                for aff in raw.get("affiliation", [])
                if aff.get("name")
            )

            authors.append(
                Author(
                    author_id=AuthorId(f"crossref:{name.lower()}"),
                    name=name,
                    orcid=str(raw.get("ORCID", "")),
                    institutions=institutions,
                )
            )
            del index

        return tuple(authors)

    def _compose_name(self, raw: dict[str, Any]) -> str:
        """用 given/family 拼名字。"""
        given = str(raw.get("given", ""))
        family = str(raw.get("family", ""))

        if given and family:
            return f"{given} {family}"

        return family or given

    def _extract_year(self, item: dict[str, Any]) -> int | None:
        """抽年份.

        ⚠️ **日期是区间** ——
        取**最早**的那个（正式出版时间，不是在线时间）。
        """
        for field in ("published-print", "published", "issued", "created"):
            parts = item.get(field, {}).get("date-parts", [])
            if parts and parts[0]:
                first = parts[0][0]
                if isinstance(first, int):
                    return first

        return None

    def _extract_venue(self, item: dict[str, Any]) -> str:
        """抽期刊/会议名。"""
        containers = item.get("container-title") or []
        return str(containers[0]) if containers else ""

    def _extract_abstract(self, item: dict[str, Any]) -> str:
        """抽摘要.

        ⚠️ **Crossref 的摘要有 JATS XML 标签** ——
        `<jats:p>...</jats:p>` 要剥掉。
        """
        raw = item.get("abstract", "")
        if not raw:
            return ""

        cleaned = _TAG_PATTERN.sub(" ", raw)
        return " ".join(cleaned.split())

    def _extract_oa(self, item: dict[str, Any]) -> OpenAccessStatus:
        """抽开放获取状态."""
        licenses = item.get("license") or []
        if licenses:
            for license_item in licenses:
                url = str(license_item.get("URL", ""))
                if "creativecommons.org" in url:
                    return OpenAccessStatus.OPEN

        # ⚠️ **没有 license 但有 link** —— 可能是免费读
        for link in item.get("link") or []:
            if link.get("content-type") == "application/pdf":
                return OpenAccessStatus.HYBRID

        return OpenAccessStatus.CLOSED

    def _map_type(self, crossref_type: str) -> PublicationType:
        """类型映射。"""
        return _TYPE_MAP.get(crossref_type, PublicationType.UNKNOWN)
