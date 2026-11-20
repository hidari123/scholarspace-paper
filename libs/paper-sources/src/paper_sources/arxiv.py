"""arXiv 适配器 —— Atom API。

⚠️ **arXiv 用 Atom（XML），不是 JSON** ——
   唯一公开的 API 就是 Atom，没有 REST JSON。

⚠️ **必须带 User-Agent** ——
   arXiv 会封禁没有 UA 的请求（返回 403）。

⚠️ **要遵守速率限制** ——
   官方建议 3 秒一个请求。
   这里不做节流（交给调用方/上层中间件）。
"""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

import httpx
from defusedxml import ElementTree as DefusedElementTree
from paper_core.application.ports import PaperSourcePort, SearchQuery
from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import (
    DOI,
    ArxivId,
    AuthorId,
    PaperId,
    SourceType,
)

__all__ = ["ArxivSource"]

#: Atom 命名空间
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}

#: ⚠️ **arXiv 自己的命名空间** —— 扩展元素（DOI、journal_ref）在里面
_ARXIV_NS = "http://arxiv.org/schemas/atom"

#: ⚠️ **完整的命名空间映射** ——
#: `ElementTree` 找 `arxiv:doi` 时要在映射里能找到 `arxiv` 前缀，
#: 否则报 `prefix 'arxiv' not found in prefix map`。
#:
#: ⚠️ **feed 里没声明这个命名空间时也不该崩** ——
#: 所以查找 DOI 用「遍历所有子节点」而不是 XPath。
_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": _ARXIV_NS,
}

#: arXiv 的 API 端点
_ARXIV_API = "https://export.arxiv.org/api/query"

#: ⚠️ **必须有 UA** —— arXiv 会封禁没有 UA 的请求
_USER_AGENT = "scholarspace-paper/0.1 (+https://github.com/hidari123/scholarspace-paper)"

#: ⚠️ **arXiv ID 格式** ——
#: 新式：`2401.00001`（4 位年 + 4~5 位序号）
#: 旧式：`hep-th/9901001`（分类 + 斜杠 + 7 位序号）
#: 两边都可能有版本后缀 `v1`
#: 年份有几位
YEAR_DIGITS = 4

#: 合理的最早年份
MIN_YEAR = 1000

#: 合理的最晚年份
MAX_YEAR = 2100

_ARXIV_ID = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})"
    r"(?:v\d+)?$"
)


class ArxivSource(PaperSourcePort):
    """arXiv 数据源.

    ⚠️ **实现 `PaperSourcePort`** ——
    上层代码不用区分数据源。
    """

    #: 数据源类型
    source = SourceType.ARXIV

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        """初始化.

        :param client: HTTP 客户端（注入以便测试）
        """
        self._client = client
        self._owns_client = client is None

    async def search(self, query: SearchQuery) -> tuple[Paper, ...]:
        """检索。

        :param query: 检索条件
        :return: 论文列表
        """
        params = self._build_params(query)

        async with self._ensure_client() as client:
            response = await client.get(_ARXIV_API, params=params)
            response.raise_for_status()

        return self._parse_atom(response.text)

    async def fetch(self, source_id: str) -> Paper | None:
        """按 arXiv ID 取单篇。

        :param source_id: arXiv ID
        :return: 论文；找不到返回 None
        """
        async with self._ensure_client() as client:
            response = await client.get(
                _ARXIV_API,
                params={"id_list": source_id, "max_results": 1},
            )
            response.raise_for_status()

        papers = self._parse_atom(response.text)
        return papers[0] if papers else None

    def _ensure_client(self) -> Any:
        """确保有 HTTP 客户端。

        ⚠️ **返回上下文管理器** ——
        自己创建的客户端要在用完后关掉。
        """
        if self._client is not None:
            return _BorrowedClient(self._client)

        return httpx.AsyncClient(
            headers={"User-Agent": _USER_AGENT},
            timeout=30.0,
            follow_redirects=True,
        )

    def _build_params(self, query: SearchQuery) -> dict[str, str | int]:
        """构造查询参数。

        ⚠️ **arXiv 的检索语法跟别的源不一样** ——
        标题用 `ti:`，作者用 `au:`，全文用 `all:`。
        """
        parts: list[str] = []

        if query.query:
            parts.append(f"all:{query.query}")
        if query.author:
            parts.append(f"au:{query.author}")
        if query.keywords:
            parts.append(" AND ".join(f"all:{keyword}" for keyword in query.keywords))

        search_query = " AND ".join(parts) if parts else "all:*"

        params: dict[str, str | int] = {
            "search_query": search_query,
            "start": query.offset,
            "max_results": min(query.limit, 100),
        }

        # ⚠️ **按提交日期排序** —— 最新的排前面
        if query.date_from is not None or query.date_to is not None:
            params["sortBy"] = "submittedDate"
            params["sortOrder"] = "descending"

        return params

    def _parse_atom(self, xml_text: str) -> tuple[Paper, ...]:
        """解析 Atom XML。

        ⚠️ **XML 解析要防 XXE** ——
        `ElementTree` 默认不解析外部实体（安全），
        但不要用 `lxml` 的默认配置。

        :param xml_text: XML 文本
        :return: 论文列表
        """
        try:
            root = _parse_xml_safely(xml_text)
        except ElementTree.ParseError:
            # ⚠️ **解析失败返回空列表** ——
            # 上游返回了垃圾数据不该让整个导入失败。
            return ()

        papers: list[Paper] = []

        for entry in root.findall("atom:entry", _ATOM_NS):
            paper = self._parse_entry(entry)
            if paper is not None:
                papers.append(paper)

        return tuple(papers)

    def _parse_entry(self, entry: ElementTree.Element) -> Paper | None:
        """解析一条 Atom entry。"""
        raw_id = self._text(entry, "atom:id")
        if not raw_id:
            return None

        # ⚠️ **arXiv 的 id 是完整 URL** —— `http://arxiv.org/abs/2401.00001v1`
        arxiv_id = self._extract_id(raw_id)
        if arxiv_id is None:
            return None

        title = " ".join((self._text(entry, "atom:title") or "").split())
        if not title:
            return None

        authors: list[Author] = []
        for index, node in enumerate(entry.findall("atom:author", _ATOM_NS)):
            name = " ".join((self._text(node, "atom:name") or "").split())
            if name:
                authors.append(Author(author_id=AuthorId(f"{arxiv_id}:{index}"), name=name))

        published = self._text(entry, "atom:published")

        return Paper(
            paper_id=PaperId(f"arxiv:{arxiv_id}"),
            title=title,
            abstract=" ".join((self._text(entry, "atom:summary") or "").split()),
            authors=tuple(authors),
            year=self._extract_year(published),
            arxiv_id=ArxivId(arxiv_id),
            source=SourceType.ARXIV,
            source_id=arxiv_id,
            doi=self._extract_doi(self._extract_child_text(entry, _ARXIV_NS, "doi")),
            pdf_url=self._extract_pdf_url(entry),
            updated_at=published or "",
        )

    def _extract_child_text(
        self,
        node: ElementTree.Element,
        namespace: str,
        tag: str,
    ) -> str | None:
        """按命名空间取子节点文本.

        ⚠️ **不用 XPath** ——
        XPath 的 `arxiv:doi` 要求前缀在命名空间映射里，
        而有些 feed 根本没声明这个命名空间 →
        直接报 `prefix 'arxiv' not found in prefix map`。

        ⚠️ **遍历所有子节点** —— 不管命名空间是什么，
        找标签名匹配的就够了。
        """
        for child in node:
            if child.tag == f"{{{namespace}}}{tag}":
                return child.text

        return None

    def _text(self, node: ElementTree.Element, path: str) -> str | None:
        """取节点文本。"""
        found = node.find(path, _ATOM_NS)
        if found is None or found.text is None:
            return None
        return found.text

    def _extract_id(self, raw_id: str) -> str | None:
        """从完整 URL 里抽 arXiv ID。

        ⚠️ **要去掉版本号后缀** ——
        `2401.00001v2` 和 `2401.00001` 是同一篇。
        """
        # ⚠️ **只去掉 URL 前缀，不能用 rsplit("/")** ——
        # 旧式 ID 本身带斜杠（`hep-th/9901001`），
        # 按斜杠切会把分类切掉，只剩 `9901001` → 匹配不上。
        tail = raw_id
        if "/" in tail and "abs/" in tail:
            tail = tail.split("abs/", 1)[-1]
        elif tail.startswith("http"):
            tail = tail.rsplit("/", 1)[-1]

        tail = tail.removesuffix(".pdf")

        if not _ARXIV_ID.match(tail):
            return None

        # ⚠️ **去掉版本号** —— `2401.00001v2` 和 `2401.00001` 是同一篇
        version_match = re.search(r"v\d+$", tail)
        if version_match is not None:
            return tail[: version_match.start()]

        return tail

    def _extract_year(self, published: str | None) -> int | None:
        """从发布时间抽年份。"""
        if not published or len(published) < YEAR_DIGITS:
            return None

        candidate = published[:YEAR_DIGITS]
        if not candidate.isdigit():
            return None

        year = int(candidate)
        return year if MIN_YEAR <= year <= MAX_YEAR else None

    def _extract_doi(self, doi: str | None) -> DOI | None:
        """抽 DOI。"""
        if not doi:
            return None

        cleaned = doi.strip().lower()
        # ⚠️ **去掉 URL 前缀** —— 有些源返回 `https://doi.org/10.1000/xxx`
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
                break

        return DOI(cleaned) if cleaned else None

    def _extract_pdf_url(self, entry: ElementTree.Element) -> str:
        """抽 PDF 链接。

        ⚠️ **要选 `application/pdf` 那个** ——
        Atom 里还有 abs 页面和别的格式。
        """
        for link in entry.findall("atom:link", _ATOM_NS):
            if link.get("type") == "application/pdf":
                return link.get("href") or ""

        return ""


def _parse_xml_safely(xml_text: str) -> ElementTree.Element:
    """安全地解析 XML.

    ⚠️ **为什么要专门处理** ——
    ruff **S314** 标记 `xml` 解析不可信数据有风险
    （XXE / 实体扩展攻击 / 账单 DDoS）。

    ⚠️ **用 `defusedxml`** ——
    它禁止实体扩展、外部实体、DTD。

    ⚠️ **为什么不用「装了才用，装了没有就退回标准库」** ——
    那样安全策略取决于环境，
    部署时忘了装就成了漏洞。
    **安全依赖必须是必选的。**
    """
    return DefusedElementTree.fromstring(xml_text)


class _BorrowedClient:
    """借用外部客户端的上下文管理器.

    ⚠️ **不关闭借来的客户端** ——
    生命周期归调用方管。
    """

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def __aenter__(self) -> httpx.AsyncClient:
        """进入。"""
        return self._client

    async def __aexit__(self, *args: object) -> None:
        """退出 —— 不关闭。"""
        return None
