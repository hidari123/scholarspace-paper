"""值对象 —— 论文领域的基础类型。

⚠️ **全部是不可变的** ——
   领域对象一旦创建就不该被改。
   要改就造新的（`replace`）。

⚠️ **ID 用 `NewType` 而不是 `str`** ——
   类型检查器能防止把 `PaperId` 传给要 `AuthorId` 的地方。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import NewType

__all__ = [
    "DOI",
    "ArxivId",
    "AuthorId",
    "OpenAccessStatus",
    "PaperId",
    "PaperStatus",
    "PublicationType",
    "SourceType",
]

#: 论文 ID
PaperId = NewType("PaperId", str)

#: 作者 ID
AuthorId = NewType("AuthorId", str)

#: arXiv 标识
ArxivId = NewType("ArxivId", str)

#: DOI（数字对象唯一标识）
DOI = NewType("DOI", str)

#: 年份有几位
YEAR_DIGITS = 4

#: 合理的最早年份（印刷术之前的不算论文）
MIN_YEAR = 1000

#: 合理的最晚年份（留点余量给未来）
MAX_YEAR = 2100


class PublicationType(StrEnum):
    """出版类型."""

    JOURNAL_ARTICLE = "journal_article"
    CONFERENCE_PAPER = "conference_paper"
    PREPRINT = "preprint"
    THESIS = "thesis"
    BOOK = "book"
    REPORT = "report"
    UNKNOWN = "unknown"


class OpenAccessStatus(StrEnum):
    """开放获取状态."""

    OPEN = "open"
    #: 全文可读但需遵守协议（如 CC BY-NC）
    GREEN = "green"
    #: 摘要可读，全文需订阅
    HYBRID = "hybrid"
    CLOSED = "closed"
    EMBARGO = "embargo"
    UNKNOWN = "unknown"


class SourceType(StrEnum):
    """来源类型."""

    ARXIV = "arxiv"
    #: PubMed / 生物医学
    PUBMED = "pubmed"
    #: Crossref（覆盖面最广）
    CROSSREF = "crossref"
    SEMANTIC_SCHOLAR = "semantic_scholar"
    OPENALEX = "openalex"
    LOCAL_UPLOAD = "local_upload"
    MANUAL = "manual"


class PaperStatus(StrEnum):
    """论文状态."""

    #: 刚导入，还没解析
    IMPORTED = "imported"
    #: 解析中
    PARSING = "parsing"
    #: 解析完成
    PARSED = "parsed"
    #: 索引完成（可被检索）
    INDEXED = "indexed"
    #: 失败
    FAILED = "failed"


def parse_year(value: str | int | None) -> int | None:
    """解析年份。

    ⚠️ **接受各种格式** —— 数据源五花八门：
    · `"2024"` → 2024
    · `"2024-03"` → 2024
    · `"2024-03-15"` → 2024
    · `"2024-03-15T10:00:00Z"` → 2024
    · `None` / `""` → None

    :param value: 年份字符串
    :return: 年份；解析不出来返回 None
    """
    if value is None:
        return None

    if isinstance(value, int):
        return value

    text = value.strip()
    if not text:
        return None

    # ⚠️ **只取前 4 位** ——
    # 完整日期的年份总在最前面。
    candidate = text[:YEAR_DIGITS]

    if len(candidate) < YEAR_DIGITS or not candidate.isdigit():
        return None

    year = int(candidate)
    # ⚠️ **合理范围检查** —— "9999" 肯定是错的
    if not MIN_YEAR <= year <= MAX_YEAR:
        return None

    return year


def parse_datetime(value: str | None) -> datetime | None:
    """解析时间戳。

    ⚠️ **接受 ISO 8601 变体** ——
    末尾的 `Z` 要先换成 `+00:00`（Python 3.11 之前不支持 `Z`）。

    :param value: 时间字符串
    :return: 时间；解析不出来返回 None
    """
    if value is None:
        return None

    text = value.strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
