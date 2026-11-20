"""服务层 —— 把仓储、导入、去重、检索串起来。

⚠️ **这一层做编排，不做业务规则** ——
   业务规则在 `paper-core` 的应用层里。
"""

from __future__ import annotations

import logging
from typing import Any

from paper_core.application.dedup import DedupDecision, DedupService
from paper_core.application.import_service import ImportReport, ImportService
from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Paper

__all__ = ["PaperNotFoundError", "PaperService", "UnsupportedSourceError"]

#: ⚠️ **模块级 logger** —— 跟项目其它服务一致
logger = logging.getLogger(__name__)


class PaperNotFoundError(Exception):
    """论文不存在.

    ⚠️ **跟「状态不对」区分开** ——
    「不存在」是 404，「参数不对」是 422。
    """


class UnsupportedSourceError(Exception):
    """不支持的数据源.

    ⚠️ 单独一个异常 —— 路由能返回 422 而不是 500。
    """


class PaperService:
    """论文服务."""

    def __init__(
        self,
        repository: Any,
        sources: dict[str, Any] | None = None,
        dedup: DedupService | None = None,
    ) -> None:
        """初始化.

        :param repository: 论文仓储
        :param sources: 数据源映射（名称 → 适配器）
        :param dedup: 去重服务
        """
        self._repository = repository
        self._sources = sources or {}
        self._dedup = dedup or DedupService()
        self._importer = ImportService(repository, dedup=self._dedup)

    # ══════════════════════════════════════════════════
    # 检索
    # ══════════════════════════════════════════════════

    async def search(
        self,
        query: SearchQuery,
        include_external: bool = False,
    ) -> tuple[Paper, ...]:
        """检索。

        ⚠️ **外部源的论文不会入库** ——
        只是临时展示，用户点了「收藏」才入库。
        入库的话，一次搜索就能塞爆数据库。

        :param query: 检索条件
        :param include_external: 是否连外部源一起搜
        :return: 论文列表
        """
        # ⚠️ **显式标注类型** —— 仓储是 `Any`（端口注入），
        # mypy 不会自动推断出 `tuple[Paper, ...]`。
        local: tuple[Paper, ...] = await self._repository.search(query)

        if not include_external:
            return local

        external = await self._search_external(query)

        # ⚠️ **外部结果排后面** —— 本地库的结果更「准」
        return local + external

    async def _search_external(self, query: SearchQuery) -> tuple[Paper, ...]:
        """搜所有外部源。

        ⚠️ **一个源失败不影响其它源** ——
        arXiv 挂了不代表 Crossref 也挂了。
        """
        results: list[Paper] = []

        for name, source in self._sources.items():
            try:
                found = await source.search(query)
            except Exception as error:  # noqa: BLE001
                # ⚠️ **单个源失败就跳过** ——
                # 不能因为一个源挂了就整个检索失败。
                #
                # ⚠️ **但要记下来** —— 静默吞掉的话，
                # 用户看到「没结果」却不知道为什么。
                logger.warning("数据源 %s 检索失败：%s", name, error)
                continue

            results.extend(found)

        return tuple(results)

    # ══════════════════════════════════════════════════
    # 单篇
    # ══════════════════════════════════════════════════

    async def get(self, paper_id: str) -> Paper:
        """取论文。

        :raises PaperNotFoundError: 不存在
        """
        # ⚠️ **显式标注类型** —— 仓储是 `Any`（端口注入）
        paper: Paper | None = await self._repository.get(paper_id)
        if paper is None:
            raise PaperNotFoundError(f"论文不存在：{paper_id}")

        return paper

    async def get_full_text(self, paper_id: str) -> str:
        """取全文。

        :raises PaperNotFoundError: 不存在
        """
        paper = await self.get(paper_id)
        return paper.full_text

    # ══════════════════════════════════════════════════
    # 导入
    # ══════════════════════════════════════════════════

    async def import_from_source(
        self,
        source_name: str,
        query: SearchQuery,
    ) -> ImportReport:
        """从数据源导入。

        :raises UnsupportedSourceError: 数据源不存在
        """
        source = self._sources.get(source_name)
        if source is None:
            raise UnsupportedSourceError(f"不支持的数据源：{source_name}")

        return await self._importer.import_from_source(source, query)

    # ══════════════════════════════════════════════════
    # 去重
    # ══════════════════════════════════════════════════

    async def check_duplicate(self, paper_id: str, candidate_id: str) -> DedupDecision:
        """判断两篇是不是同一篇。

        :raises PaperNotFoundError: 有一篇不存在
        """
        existing = await self.get(paper_id)
        candidate = await self.get(candidate_id)

        return self._dedup.decide(existing, candidate)

    async def merge(self, paper_id: str, candidate_id: str) -> Paper:
        """合并两篇。

        ⚠️ **合并到「主记录」** —— `paper_id` 是主记录，
        `candidate_id` 是补充来源。

        :raises PaperNotFoundError: 有一篇不存在
        """
        existing = await self.get(paper_id)
        candidate = await self.get(candidate_id)

        merged = self._dedup.merge(existing, candidate)
        await self._repository.save(merged)

        return merged

    # ══════════════════════════════════════════════════
    # 删除
    # ══════════════════════════════════════════════════

    async def delete(self, paper_id: str) -> bool:
        """删除论文。

        ⚠️ **幂等** —— 不存在也返回成功。
        """
        deleted: bool = await self._repository.delete(paper_id)
        return deleted
