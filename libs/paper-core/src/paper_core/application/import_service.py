"""导入服务 —— 从数据源拉取 → 去重 → 入库。

⚠️ **导入是最容易出重复数据的地方** ——
   同一篇论文被反复导入、多个数据源有同一篇、
   用户手动上传的又是同一篇。

⚠️ **流程**：
    ① 拉取（数据源）
    ② 按 DOI/arXiv 精确查重
    ③ 逐条做「标题级」去重判定
    ④ 合并入库
"""

from __future__ import annotations

from dataclasses import dataclass, field

from paper_core.application.dedup import DedupService
from paper_core.application.ports import PaperRepositoryPort, SearchQuery
from paper_core.domain.entities import Paper

__all__ = ["ImportReport", "ImportService"]


@dataclass(frozen=True, slots=True)
class ImportReport:
    """导入报告.

    ⚠️ **必须有报告** ——
    静默导入几十条，用户不知道实际入库了几条。
    """

    #: 拉取到的总数
    fetched: int = 0
    #: 新增
    inserted: int = 0
    #: 更新（合并）
    updated: int = 0
    #: 跳过（已存在且无新信息）
    skipped: int = 0
    #: 失败的来源 ID
    failed: tuple[str, ...] = ()
    #: 每条的处理说明
    details: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total_processed(self) -> int:
        """处理总数。"""
        return self.inserted + self.updated + self.skipped


class ImportService:
    """导入服务."""

    def __init__(
        self,
        repository: PaperRepositoryPort,
        dedup: DedupService | None = None,
    ) -> None:
        """初始化。

        :param repository: 论文仓储
        :param dedup: 去重服务
        """
        self._repository = repository
        self._dedup = dedup or DedupService()

    async def import_papers(self, papers: tuple[Paper, ...]) -> ImportReport:
        """导入一批论文。

        ⚠️ **先查精确重复，再做模糊判定** ——
        精确查重是 O(1)，模糊判定要遍历全库。

        :param papers: 待导入的论文
        :return: 导入报告
        """
        inserted = 0
        updated = 0
        skipped = 0
        details: list[str] = []

        for paper in papers:
            outcome = await self._import_one(paper)
            details.append(outcome)

            if outcome.startswith("新增"):
                inserted += 1
            elif outcome.startswith("合并"):
                updated += 1
            else:
                skipped += 1

        return ImportReport(
            fetched=len(papers),
            inserted=inserted,
            updated=updated,
            skipped=skipped,
            details=tuple(details),
        )

    async def import_from_source(
        self,
        source: object,
        query: SearchQuery,
    ) -> ImportReport:
        """从数据源导入。

        :param source: 数据源（实现 `PaperSourcePort`）
        :param query: 检索条件
        :return: 导入报告
        """
        papers = await source.search(query)  # type: ignore[attr-defined]
        return await self.import_papers(papers)

    async def _import_one(self, paper: Paper) -> str:
        """导入一篇。

        ⚠️ **三步查重**：
            ① 精确查重（canonical_key）—— O(1)
            ② 按 ID 查 —— O(1)
            ③ **模糊查重** —— 遍历全库，跨来源必需

        :return: 处理说明
        """
        # ① 精确查重 —— DOI / arXiv / 来源 ID
        existing = await self._repository.find_by_canonical_key(paper.canonical_key())

        # ② 按 ID 查
        if existing is None:
            existing = await self._repository.get(paper.paper_id)

        # ③ 模糊查重 —— ⚠️ **跨来源必需** ——
        #    arXiv 的 key 是 `arxiv:xxx`，Crossref 的是 `doi:yyy`，
        #    精确查重永远找不到对方。
        if existing is None:
            existing = await self._find_fuzzy_match(paper)

        if existing is None:
            await self._repository.save(paper)
            return f"新增：{paper.title[:50]}"

        # ④ 模糊判定
        decision = self._dedup.decide(existing, paper)

        if not decision.is_same:
            await self._repository.save(paper)
            return f"新增（判定为不同论文）：{paper.title[:50]}"

        # ⑤ 合并
        merged = self._dedup.merge(existing, paper)
        await self._repository.save(merged)

        if merged == existing:
            return f"跳过（已存在）：{paper.title[:50]}"

        return f"合并：{paper.title[:50]}（{decision.reason}）"

    async def _find_fuzzy_match(self, paper: Paper) -> Paper | None:
        """在已有论文里找模糊匹配。

        ⚠️ **遍历全库** —— 真实实现应该靠数据库的
        「标题归一化后完全相等」索引来找。

        :param paper: 待查论文
        :return: 匹配到的论文；没有返回 None
        """
        for existing in await self._repository.list_all():
            if self._dedup.decide(existing, paper).is_same:
                return existing

        return None
