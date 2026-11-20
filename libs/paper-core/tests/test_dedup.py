"""去重服务测试。

⚠️ **重点验证「分级判定」**：
    ① DOI 完全匹配   → 100%
    ② arXiv ID 匹配  → 98%
    ③ 标题+作者+年份 → 95%
    ④ 标题+年份      → 60%（需要人工确认）
"""

from __future__ import annotations

from dataclasses import replace

from paper_core.application.dedup import DedupService, normalize_title
from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import (
    DOI,
    ArxivId,
    AuthorId,
    OpenAccessStatus,
    PaperId,
    SourceType,
)


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


class TestNormalizeTitle:
    """标题归一化。"""

    def test_lowercases(self) -> None:
        """转小写。"""
        assert normalize_title("Deep Learning") == "deep learning"

    def test_removes_punctuation(self) -> None:
        """去标点。"""
        assert normalize_title("Deep Learning, Part 2!") == "deep learning part 2"

    def test_removes_stop_words(self) -> None:
        """删停用词 —— 它们不影响论文身份。

        ⚠️ "of" 也是停用词 —— "The Effect of A Study" 和
        "The Effect Study" 是同一篇。
        """
        assert normalize_title("The Effect of A Study") == "effect study"

    def test_normalizes_fullwidth_characters(self) -> None:
        """⚠️ **NFKC 归一化** —— 全角半角要归到一起。"""
        assert normalize_title("Ｎｅural Networks") == "neural networks"

    def test_collapses_whitespace(self) -> None:
        """压空白。"""
        assert normalize_title("Deep    Learning") == "deep learning"

    def test_empty_title(self) -> None:
        """空标题不崩。"""
        assert normalize_title("") == ""


class TestDecide:
    """判定."""

    def test_same_doi(self) -> None:
        """① DOI 完全匹配。"""
        existing = make_paper(doi="10.1000/xyz")
        candidate = make_paper(
            title="Completely Different Title",
            source=SourceType.CROSSREF,
            source_id="crossref-1",
            doi="10.1000/XYZ",
        )

        decision = DedupService().decide(existing, candidate)

        assert decision.is_same
        assert decision.confidence == 1.0

    def test_different_doi(self) -> None:
        """DOI 不同 → 不同论文。"""
        existing = make_paper(doi="10.1000/a", title="Paper A")
        candidate = make_paper(doi="10.1000/b", title="Paper B")

        decision = DedupService().decide(existing, candidate)

        assert not decision.is_same

    def test_same_arxiv_id(self) -> None:
        """② arXiv ID 匹配。"""
        existing = make_paper(arxiv_id="2401.00001")
        candidate = make_paper(
            title="Different Title Here",
            source=SourceType.CROSSREF,
            source_id="cr-1",
            arxiv_id="2401.00001",
        )

        decision = DedupService().decide(existing, candidate)

        assert decision.is_same
        assert decision.confidence > 0.9

    def test_same_title_author_year(self) -> None:
        """③ 标题 + 第一作者 + 年份。"""
        existing = make_paper()
        candidate = make_paper(
            source=SourceType.CROSSREF,
            source_id="cr-1",
            year=2024,
        )

        decision = DedupService().decide(existing, candidate)

        assert decision.is_same
        assert decision.confidence > 0.9

    def test_same_title_different_author(self) -> None:
        """⚠️ **标题一样但作者不同** —— 可能同名不同篇。"""
        existing = make_paper(authors=("John Smith",))
        candidate = make_paper(
            authors=("Jane Doe",),
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        decision = DedupService().decide(existing, candidate)

        # ⚠️ 年份相同 → 判定为「是」但置信度低
        assert decision.is_same
        assert decision.confidence < 0.9

    def test_different_titles(self) -> None:
        """标题不同 → 不同论文。"""
        existing = make_paper(title="Paper About Cats")
        candidate = make_paper(
            title="Paper About Dogs",
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        decision = DedupService().decide(existing, candidate)

        assert not decision.is_same

    def test_title_difference_from_punctuation(self) -> None:
        """⚠️ **标点差异不算不同** —— "A-B" 和 "AB" 一样。"""
        existing = make_paper(title="Attention-Is-All-You-Need")
        candidate = make_paper(
            title="Attention Is All You Need",
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        decision = DedupService().decide(existing, candidate)

        assert decision.is_same

    def test_author_name_format_variants(self) -> None:
        """⚠️ **作者名格式差异不算不同**。"""
        existing = make_paper(authors=("John Smith",))
        candidate = make_paper(
            authors=("J. Smith",),
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        decision = DedupService().decide(existing, candidate)

        # ⚠️ "john smith" vs "j smith" 归一化后不同
        #    但年份相同 → 判定为「是」（低置信度）
        assert decision.is_same

    def test_year_tolerance(self) -> None:
        """⚠️ **年份容差 1 年** —— 预印本和正式版常差一年。"""
        existing = make_paper(year=2024)
        candidate = make_paper(year=2025, source=SourceType.CROSSREF, source_id="cr-1")

        decision = DedupService().decide(existing, candidate)

        assert decision.is_same

    def test_different_years_not_close(self) -> None:
        """年份差太多 → 不同。"""
        existing = make_paper(title="A Study", year=2000)
        candidate = make_paper(
            title="A Study",
            year=2024,
            authors=("Someone Else",),
            source=SourceType.CROSSREF,
            source_id="cr-1",
        )

        decision = DedupService().decide(existing, candidate)

        assert not decision.is_same


class TestMerge:
    """合并."""

    def test_merges_abstract(self) -> None:
        """⚠️ **有摘要的补上摘要**。"""
        existing = make_paper()
        candidate = make_paper(
            source=SourceType.CROSSREF,
            source_id="cr-1",
            abstract="A detailed abstract from Crossref.",
        )

        merged = DedupService().merge(existing, candidate)

        assert merged.abstract == "A detailed abstract from Crossref."

    def test_merges_doi(self) -> None:
        """补 DOI。"""
        existing = make_paper()
        candidate = make_paper(
            source=SourceType.CROSSREF,
            source_id="cr-1",
            doi="10.1000/xyz",
        )

        merged = DedupService().merge(existing, candidate)

        assert merged.doi == DOI("10.1000/xyz")

    def test_keeps_existing_abstract_if_longer(self) -> None:
        """⚠️ **更全的赢** —— 现有摘要更长就保留现有的。"""
        existing = make_paper(abstract="A much longer abstract that has more detail.")
        candidate = make_paper(
            source=SourceType.CROSSREF,
            source_id="cr-1",
            abstract="Short.",
        )

        merged = DedupService().merge(existing, candidate)

        assert merged.abstract == "A much longer abstract that has more detail."

    def test_merges_citation_count_takes_max(self) -> None:
        """⚠️ **引用数取大的**。"""
        existing = replace(make_paper(), citation_count=10)
        candidate = replace(
            make_paper(source=SourceType.CROSSREF, source_id="cr-1"),
            citation_count=50,
        )

        merged = DedupService().merge(existing, candidate)

        assert merged.citation_count == 50


class TestCanonicalKey:
    """去重键."""

    def test_prefers_doi(self) -> None:
        """⚠️ **优先 DOI** —— 最权威的标识。"""
        paper = make_paper(doi="10.1000/XYZ", arxiv_id="2401.00001")

        assert paper.canonical_key() == "doi:10.1000/xyz"

    def test_falls_back_to_arxiv(self) -> None:
        """没有 DOI 就用 arXiv。"""
        paper = make_paper(arxiv_id="2401.00001")

        assert paper.canonical_key() == "arxiv:2401.00001"

    def test_falls_back_to_source(self) -> None:
        """都没有就用来源 ID。"""
        paper = make_paper()

        assert paper.canonical_key() == "arxiv:2401.00001"


class TestOpenAccess:
    """开放获取."""

    def test_open_is_open_access(self) -> None:
        """开放获取。"""
        paper = replace(make_paper(), open_access=OpenAccessStatus.OPEN)

        assert paper.is_open_access()

    def test_closed_is_not_open_access(self) -> None:
        """⚠️ **闭源不是开放获取**。"""
        paper = replace(make_paper(), open_access=OpenAccessStatus.CLOSED)

        assert not paper.is_open_access()
