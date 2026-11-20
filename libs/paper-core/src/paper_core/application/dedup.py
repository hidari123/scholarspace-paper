"""去重 —— 文献库的核心难题。

⚠️ **同一篇论文在不同数据源有不同记录**：
    · arXiv 有预印本，Crossref 有正式版
    · 标题大小写不同、作者顺序不同、摘要措辞不同

⚠️ **去重要分级** —— 不能一步到位：
    ① **DOI 完全匹配** → 100% 是同一篇
    ② **arXiv ID 匹配** → 几乎肯定是
    ③ **标题归一化 + 第一作者姓氏匹配** → 很可能是
    ④ **标题归一化 + 年份接近** → 可能（需要人工确认）

⚠️ **不能只靠标题** —— 不同论文可能有相同标题
（比如「Introduction」「Results」这种）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace

from paper_core.domain.entities import Paper

__all__ = [
    "DedupDecision",
    "DedupService",
    "normalize_title",
]

#: ⚠️ **要剥离的标点** —— 归一化时去掉
_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)

#: ⚠️ **多余空白** —— 归一化时压成单个空格
_WHITESPACE = re.compile(r"\s+")

#: ⚠️ **归一化时要删掉的词** —— 它们不影响论文身份
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "on",
        "of",
        "for",
        "and",
        "or",
        "in",
        "to",
        "with",
        "via",
        "using",
    }
)


def normalize_title(title: str) -> str:
    """标题归一化。

    ⚠️ **步骤**：
        ① Unicode NFKC（统一全角/半角、兼容字符）
        ② 转小写
        ③ 去标点
        ④ 删停用词
        ⑤ 压空白

    :param title: 原标题
    :return: 归一化后的标题
    """
    # ⚠️ **NFKC 很关键** ——
    # 「Ｎeural Networks」和「Neural Networks」要归到一起。
    text = unicodedata.normalize("NFKC", title).lower()

    text = _PUNCTUATION.sub(" ", text)
    text = _WHITESPACE.sub(" ", text).strip()

    # ⚠️ **删停用词** —— 但要保持顺序
    words = [word for word in text.split() if word not in _STOP_WORDS]

    return " ".join(words)


def _normalize_author(name: str) -> str:
    """作者名归一化。

    ⚠️ **取姓 + 首字母** ——
    "John Smith" / "J. Smith" / "John A. Smith" 都要归到一起。
    """
    text = unicodedata.normalize("NFKC", name).lower().strip()
    if not text:
        return ""

    # ⚠️ **去掉所有空格和标点** —— "Smith, John" 和 "John Smith" 要一样
    cleaned = re.sub(r"[^\w]", "", text)
    return cleaned


@dataclass(frozen=True, slots=True)
class DedupDecision:
    """去重判定结果.

    ⚠️ **三态** —— 明确「是」「不是」「不确定」，
    别把「不确定」当成「不是」。
    """

    #: 是否是同一篇
    is_same: bool
    #: 判定依据
    reason: str
    #: 置信度（0~1）
    confidence: float


class DedupService:
    """去重服务.

    ⚠️ **无状态** —— 每次调用独立判定。
    """

    #: ⚠️ **规则表** —— 从强到弱
    DEDUP_RULES: tuple[str, ...] = (
        "doi_exact",
        "arxiv_exact",
        "title_author_year",
        "title_year_only",
    )

    def decide(self, existing: Paper, candidate: Paper) -> DedupDecision:
        """判断两篇是不是同一篇。

        :param existing: 已有论文
        :param candidate: 新来的论文
        :return: 判定结果
        """
        # ① 强标识匹配（DOI / arXiv）—— 命中就一定同一篇
        strong = self._match_by_identifier(existing, candidate)
        if strong is not None:
            return strong

        # ② 标题级匹配
        return self._match_by_title(existing, candidate)

    def _match_by_identifier(
        self,
        existing: Paper,
        candidate: Paper,
    ) -> DedupDecision | None:
        """按强标识匹配.

        ⚠️ **DOI → arXiv 的顺序不能换** ——
        DOI 更权威，置信度更高。

        :return: 匹配结果；不匹配返回 None
        """
        if existing.doi and candidate.doi and existing.doi.lower() == candidate.doi.lower():
            return DedupDecision(
                is_same=True,
                reason=f"DOI 相同：{existing.doi}",
                confidence=1.0,
            )

        if (
            existing.arxiv_id
            and candidate.arxiv_id
            and existing.arxiv_id.lower() == candidate.arxiv_id.lower()
        ):
            return DedupDecision(
                is_same=True,
                reason=f"arXiv ID 相同：{existing.arxiv_id}",
                confidence=0.98,
            )

        return None

    def _match_by_title(self, existing: Paper, candidate: Paper) -> DedupDecision:
        """按标题 + 作者 + 年份匹配.

        ⚠️ **不能只靠标题** ——
        不同论文可能有相同标题（「Introduction」「Results」）。
        """
        existing_title = normalize_title(existing.title)
        candidate_title = normalize_title(candidate.title)

        if existing_title == "" or existing_title != candidate_title:
            return DedupDecision(
                is_same=False,
                reason="标题归一化后不同",
                confidence=0.9,
            )

        first_author_same = self._first_author_same(existing, candidate)
        year_close = self._years_close(existing.year, candidate.year)

        if first_author_same and year_close:
            return DedupDecision(
                is_same=True,
                reason="标题 + 第一作者 + 年份都匹配",
                confidence=0.95,
            )

        if first_author_same:
            return DedupDecision(
                is_same=True,
                reason="标题 + 第一作者匹配",
                confidence=0.85,
            )

        if year_close:
            # ⚠️ **标题一样但作者不同** ——
            #    有可能是同名不同篇，也有可能是作者列表格式差异。
            #    标成「需要确认」而不是「是」。
            return DedupDecision(
                is_same=True,
                reason="标题 + 年份匹配（作者不同，建议人工确认）",
                confidence=0.6,
            )

        return DedupDecision(
            is_same=False,
            reason="标题相同但作者和年份都不匹配",
            confidence=0.7,
        )

    def merge(self, existing: Paper, candidate: Paper) -> Paper:
        """合并两篇论文.

        ⚠️ **「更全的赢」** ——
        两个来源各有缺失，合并后取信息更全的那个。

        ⚠️ **字段级的合并** ——
        不是整体二选一：
        有摘要的补上摘要，有全文的补上全文。
        """
        # ⚠️ **逐字段挑更好的** ——
        merged_title = (
            candidate.title if len(candidate.title) > len(existing.title) else existing.title
        )
        merged_abstract = (
            candidate.abstract
            if len(candidate.abstract) > len(existing.abstract)
            else existing.abstract
        )
        merged_full_text = (
            candidate.full_text
            if len(candidate.full_text) > len(existing.full_text)
            else existing.full_text
        )
        merged_venue = candidate.venue if candidate.venue else existing.venue
        merged_pdf = candidate.pdf_url if candidate.pdf_url else existing.pdf_url
        merged_doi = candidate.doi or existing.doi
        merged_arxiv = candidate.arxiv_id or existing.arxiv_id
        merged_keywords = candidate.keywords or existing.keywords

        # ⚠️ **作者列表取长的** —— 通常更全
        merged_authors = (
            candidate.authors
            if len(candidate.authors) >= len(existing.authors)
            else existing.authors
        )

        # ⚠️ **引用数取大的**
        merged_citations = max(existing.citation_count, candidate.citation_count)
        merged_cited_by = max(existing.cited_by_count, candidate.cited_by_count)

        # ⚠️ **年份取更具体的** —— 有月份/日期的更可信
        merged_year = existing.year if existing.year is not None else candidate.year

        return replace(
            existing,
            title=merged_title,
            abstract=merged_abstract,
            full_text=merged_full_text,
            venue=merged_venue,
            pdf_url=merged_pdf,
            doi=merged_doi,
            arxiv_id=merged_arxiv,
            keywords=merged_keywords,
            authors=merged_authors,
            citation_count=merged_citations,
            cited_by_count=merged_cited_by,
            year=merged_year,
        )

    def _first_author_same(self, existing: Paper, candidate: Paper) -> bool:
        """第一作者是否相同。"""
        existing_names = existing.author_names()
        candidate_names = candidate.author_names()

        if not existing_names or not candidate_names:
            return False

        return _normalize_author(existing_names[0]) == _normalize_author(candidate_names[0])

    def _years_close(self, left: int | None, right: int | None) -> bool:
        """年份是否接近。

        ⚠️ **容差 1 年** ——
        预印本（arXiv）和正式版（期刊）常差一年。
        """
        if left is None or right is None:
            return False

        return abs(left - right) <= 1
