"""值对象测试 —— 重点是「脏数据解析」。

⚠️ **数据源什么都往里塞** ——
   年份可能是 `"2024"` / `"2024-03"` / `"2024-03-15"` / `null` / `""`。
"""

from __future__ import annotations

import pytest

from paper_core.domain.entities import Author, Paper
from paper_core.domain.value_objects import (
    AuthorId,
    PaperId,
    PaperStatus,
    SourceType,
    parse_datetime,
    parse_year,
)


class TestParseYear:
    """年份解析."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("2024", 2024),
            ("2024-03", 2024),
            ("2024-03-15", 2024),
            ("2024-03-15T10:00:00Z", 2024),
            ("  2024  ", 2024),
            (2024, 2024),
        ],
    )
    def test_valid_formats(self, value: object, expected: int) -> None:
        """⚠️ **各种格式都要能解析**。"""
        assert parse_year(value) == expected  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", [None, "", "   ", "unknown", "24"])
    def test_invalid_formats(self, value: object) -> None:
        """⚠️ **解析不出来返回 None** —— 不能抛异常。"""
        assert parse_year(value) is None  # type: ignore[arg-type]

    @pytest.mark.parametrize("value", ["0000", "9999", "2101"])
    def test_out_of_range(self, value: str) -> None:
        """合理范围检查。

        ⚠️ "9999" 肯定是错的。
        ⚠️ "10000" 取前 4 位是 "1000" —— 在范围内，不算错。
        """
        assert parse_year(value) is None


class TestParseDatetime:
    """时间解析."""

    def test_iso_with_z(self) -> None:
        """⚠️ **末尾的 Z 要转成 +00:00**。"""
        parsed = parse_datetime("2024-03-15T10:00:00Z")

        assert parsed is not None
        assert parsed.year == 2024

    def test_iso_with_offset(self) -> None:
        """带时区偏移。"""
        parsed = parse_datetime("2024-03-15T10:00:00+08:00")

        assert parsed is not None
        assert parsed.hour == 10

    def test_plain_date(self) -> None:
        """纯日期。"""
        parsed = parse_datetime("2024-03-15")

        assert parsed is not None
        assert parsed.month == 3

    @pytest.mark.parametrize("value", [None, "", "not a date"])
    def test_invalid(self, value: object) -> None:
        """解析不出来返回 None。"""
        assert parse_datetime(value) is None  # type: ignore[arg-type]


class TestPaperFromSource:
    """从来源构造."""

    def test_generates_id_from_source(self) -> None:
        """⚠️ **ID 从来源 + 来源主键生成** —— 保证跨来源不撞。"""
        paper = Paper.from_source(
            SourceType.ARXIV,
            "2401.00001",
            "Title",
        )

        assert paper.paper_id == PaperId("arxiv:2401.00001")

    def test_parses_year(self) -> None:
        """⚠️ **年份在构造时就解析** —— 各处解析会不一致。"""
        paper = Paper.from_source(
            SourceType.CROSSREF,
            "cr-1",
            "Title",
            year="2024-03-15",
        )

        assert paper.year == 2024

    def test_parses_updated_at(self) -> None:
        """更新时间也要解析。"""
        paper = Paper.from_source(
            SourceType.CROSSREF,
            "cr-1",
            "Title",
            updated_at="2024-03-15T10:00:00Z",
        )

        assert paper.updated_at.startswith("2024-03-15")


class TestPaperBehaviour:
    """论文行为."""

    def test_author_names(self) -> None:
        """作者名列表。"""
        paper = Paper(
            paper_id=PaperId("p1"),
            title="Title",
            authors=(
                Author(author_id=AuthorId("a1"), name="John Smith"),
                Author(author_id=AuthorId("a2"), name="Jane Doe"),
            ),
        )

        assert paper.author_names() == ("John Smith", "Jane Doe")

    def test_no_full_text_does_not_crash(self) -> None:
        """⚠️ **没有全文时不能崩**。"""
        paper = Paper(paper_id=PaperId("p1"), title="Title")

        assert not paper.has_full_text()

    def test_has_full_text(self) -> None:
        """有没有全文。"""
        paper = Paper(paper_id=PaperId("p1"), title="Title")
        assert not paper.has_full_text()

        with_text = paper.with_full_text("Some content")
        assert with_text.has_full_text()

    def test_with_status_returns_copy(self) -> None:
        """⚠️ **换状态要产生新对象** —— 原对象不能变。"""
        paper = Paper(paper_id=PaperId("p1"), title="Title")
        updated = paper.with_status(PaperStatus.PARSED)

        assert paper.status is PaperStatus.IMPORTED
        assert updated.status is PaperStatus.PARSED
