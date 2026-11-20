"""实体 —— 论文、作者、机构、引用关系。

⚠️ **实体有身份**（ID），值对象没有。
   论文改了标题还是同一篇论文；作者换了顺序还是同一个人。
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from paper_core.domain.value_objects import (
    DOI,
    ArxivId,
    AuthorId,
    OpenAccessStatus,
    PaperId,
    PaperStatus,
    PublicationType,
    SourceType,
    parse_datetime,
    parse_year,
)

__all__ = [
    "Author",
    "Citation",
    "Institution",
    "Paper",
    "PaperAuthor",
]


@dataclass(frozen=True, slots=True)
class Institution:
    """机构."""

    #: 机构 ID
    institution_id: str
    #: 名称
    name: str
    #: 国家代码（ISO 3166-1 alpha-2）
    country_code: str = ""
    #: ROR ID（研究机构注册系统）
    ror_id: str = ""


@dataclass(frozen=True, slots=True)
class Author:
    """作者."""

    #: 作者 ID
    author_id: AuthorId
    #: 显示名
    name: str
    #: ORCID（研究者唯一标识）
    orcid: str = ""
    #: 机构列表
    institutions: tuple[Institution, ...] = ()


@dataclass(frozen=True, slots=True)
class PaperAuthor:
    """论文-作者关联.

    ⚠️ **单独一个实体** ———
    作者在论文里的顺序很重要（第一作者 vs 通讯作者），
    而且同一作者在不同论文里的机构可能不同。
    """

    #: 论文 ID
    paper_id: PaperId
    #: 作者 ID
    author_id: AuthorId
    #: 顺序（从 1 开始）
    position: int
    #: 是否通讯作者
    is_corresponding: bool = False
    #: 该论文里的署名
    name_as_listed: str = ""


@dataclass(frozen=True, slots=True)
class Citation:
    """引用关系.

    ⚠️ **「谁引用了谁」是有向的** ——
    A 引用 B 和 B 引用 A 是两回事。
    """

    #: 引用方（发起引用的论文）
    citing_paper_id: PaperId
    #: 被引方（被引用的论文）
    cited_paper_id: PaperId
    #: 上下文片段
    context: str = ""
    #: 是否是元数据引用（没有原文上下文）
    is_metadata_only: bool = True


@dataclass(frozen=True, slots=True)
class Paper:
    """论文.

    ⚠️ **核心实体** —— 文献库的一切都围着它转。
    """

    #: 论文 ID
    paper_id: PaperId
    #: 标题
    title: str
    #: 摘要
    abstract: str = ""
    #: 作者列表（按顺序）
    authors: tuple[Author, ...] = ()
    #: 出版年份
    year: int | None = None
    #: 出版类型
    publication_type: PublicationType = PublicationType.UNKNOWN
    #: 开放获取状态
    open_access: OpenAccessStatus = OpenAccessStatus.UNKNOWN
    #: 期刊/会议名
    venue: str = ""
    #: 卷
    volume: str = ""
    #: 期
    issue: str = ""
    #: 页码
    pages: str = ""
    #: DOI
    doi: DOI | None = None
    #: arXiv ID
    arxiv_id: ArxivId | None = None
    #: 出版商
    publisher: str = ""
    #: 引用数
    citation_count: int = 0
    #: 被引用数
    cited_by_count: int = 0
    #: 引用了哪些论文
    references: tuple[PaperId, ...] = ()
    #: 来源
    source: SourceType = SourceType.MANUAL
    #: 原始来源 ID（各数据源的主键）
    source_id: str = ""
    #: 全文 URL
    pdf_url: str = ""
    #: 状态
    status: PaperStatus = PaperStatus.IMPORTED
    #: 关键词
    keywords: tuple[str, ...] = ()
    #: 全文（如果有）
    full_text: str = ""
    #: 最后更新时间
    updated_at: str = ""

    # ══════════════════════════════════════════════════
    # 构造辅助
    # ══════════════════════════════════════════════════

    @classmethod
    def from_source(
        cls,
        source: SourceType,
        source_id: str,
        title: str,
        **kwargs: object,
    ) -> Paper:
        """从外部数据源构造。

        ⚠️ **年份/时间统一在这里解析** ——
        各数据源的格式五花八门，
        解析逻辑散落在各处会不一致。

        :param source: 来源
        :param source_id: 来源主键
        :param title: 标题
        :param kwargs: 其它字段
        """
        raw_year = kwargs.pop("year", None)
        raw_updated = kwargs.pop("updated_at", None)

        # ⚠️ **类型窄化要显式做** ——
        # `kwargs` 是 `object`，mypy 不会自动窄化 isinstance 之后的结果
        # （对 `parse_datetime` 的返回值尤其如此）。
        year_value: int | None = None
        if isinstance(raw_year, int):
            year_value = raw_year
        elif isinstance(raw_year, str):
            year_value = parse_year(raw_year)

        updated_value = ""
        if isinstance(raw_updated, str):
            parsed = parse_datetime(raw_updated)
            updated_value = parsed.isoformat() if parsed is not None else ""

        return cls(
            paper_id=PaperId(f"{source.value}:{source_id}"),
            title=title,
            source=source,
            source_id=source_id,
            year=year_value,
            updated_at=updated_value or "",
            **kwargs,  # type: ignore[arg-type]
        )

    # ══════════════════════════════════════════════════
    # 行为
    # ══════════════════════════════════════════════════

    def with_status(self, status: PaperStatus) -> Paper:
        """换状态的副本。"""
        return replace(self, status=status)

    def with_full_text(self, full_text: str) -> Paper:
        """带全文的副本。"""
        return replace(self, full_text=full_text)

    def author_names(self) -> tuple[str, ...]:
        """作者名列表。"""
        return tuple(author.name for author in self.authors)

    def is_open_access(self) -> bool:
        """是否开放获取。"""
        return self.open_access in (
            OpenAccessStatus.OPEN,
            OpenAccessStatus.GREEN,
        )

    def has_full_text(self) -> bool:
        """有没有全文。"""
        return bool(self.full_text.strip())

    def canonical_key(self) -> str:
        """去重键.

        ⚠️ **优先 DOI** —— 它是最权威的标识。
        没有 DOI 就用 arXiv ID，再没有就用来源 ID。

        ⚠️ **这个键用于跨来源去重** ——
        同一篇论文可能同时在 arXiv 和 Crossref 里有记录。
        """
        if self.doi:
            return f"doi:{self.doi.lower()}"
        if self.arxiv_id:
            return f"arxiv:{self.arxiv_id.lower()}"
        return f"{self.source.value}:{self.source_id}"
