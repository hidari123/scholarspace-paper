"""论文路由 —— 检索 / 单篇 / 删除 / 去重检查."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from paper_core.application.ports import SearchQuery
from paper_core.domain.entities import Paper

from paper_http.schemas import (
    AuthorResponse,
    DedupDecisionResponse,
    PaperResponse,
    SearchRequest,
)
from paper_http.service import PaperNotFoundError

__all__ = ["router", "set_service"]

router = APIRouter(prefix="/api/v1/papers", tags=["papers"])

#: 论文服务 —— 由 app 工厂注入。
_service: Any = None


def set_service(service: Any) -> None:
    """设置论文服务.

    ⚠️ 在 `create_app()` 里调用一次。
    """
    global _service  # noqa: PLW0603
    _service = service


def _svc() -> Any:
    """取服务.

    :raises HTTPException: 没配置服务
    """
    if _service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="服务未配置",
        )
    return _service


def to_response(paper: Paper) -> PaperResponse:
    """领域对象 → 响应模型."""
    return PaperResponse(
        paper_id=paper.paper_id,
        title=paper.title,
        abstract=paper.abstract,
        authors=[
            AuthorResponse(
                author_id=author.author_id,
                name=author.name,
                orcid=author.orcid,
                institutions=[item.name for item in author.institutions],
            )
            for author in paper.authors
        ],
        year=paper.year,
        publication_type=paper.publication_type.value,
        open_access=paper.open_access.value,
        venue=paper.venue,
        volume=paper.volume,
        issue=paper.issue,
        pages=paper.pages,
        doi=paper.doi,
        arxiv_id=paper.arxiv_id,
        publisher=paper.publisher,
        citation_count=paper.citation_count,
        cited_by_count=paper.cited_by_count,
        keywords=list(paper.keywords),
        source=paper.source.value,
        source_id=paper.source_id,
        pdf_url=paper.pdf_url,
        status=paper.status.value,
        # ⚠️ **全文不在响应里** —— 只给一个「有没有」的标志
        has_full_text=paper.has_full_text(),
    )


@router.post("/search", response_model=list[PaperResponse])
async def search_papers_endpoint(payload: SearchRequest) -> list[PaperResponse]:
    """检索论文.

    ⚠️ **POST 而不是 GET** ——
    检索条件太复杂，GET 的 query string 装不下。
    """
    query = SearchQuery(
        query=payload.query,
        author=payload.author,
        venue=payload.venue,
        keywords=tuple(payload.keywords),
        date_from=payload.date_from,
        date_to=payload.date_to,
        open_access_only=payload.open_access_only,
        limit=payload.limit,
        offset=payload.offset,
    )

    papers = await _svc().search(query, include_external=payload.include_external)

    return [to_response(paper) for paper in papers]


@router.get("/{paper_id}", response_model=PaperResponse)
async def get_paper_endpoint(paper_id: str) -> PaperResponse:
    """取论文.

    Raises:
        HTTPException: 不存在（404）
    """
    try:
        paper = await _svc().get(paper_id)
    except PaperNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return to_response(paper)


@router.get("/{paper_id}/full-text", response_model=str)
async def get_full_text_endpoint(paper_id: str) -> str:
    """取全文.

    ⚠️ **单独一个端点** —— 全文很大，
    不该塞进列表响应里。

    Raises:
        HTTPException: 不存在（404）
    """
    try:
        # ⚠️ **显式标注类型** —— 服务是 `Any`（端口注入）
        full_text: str = await _svc().get_full_text(paper_id)
    except PaperNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return full_text


@router.delete("/{paper_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_paper_endpoint(paper_id: str) -> None:
    """删除论文.

    ⚠️ **幂等** —— 不存在也返回 204。
    """
    await _svc().delete(paper_id)


@router.get(
    "/{paper_id}/duplicate/{candidate_id}",
    response_model=DedupDecisionResponse,
)
async def check_duplicate_endpoint(
    paper_id: str,
    candidate_id: str,
) -> DedupDecisionResponse:
    """检查两篇是不是重复.

    Raises:
        HTTPException: 有一篇不存在（404）
    """
    try:
        decision = await _svc().check_duplicate(paper_id, candidate_id)
    except PaperNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return DedupDecisionResponse(
        is_same=decision.is_same,
        reason=decision.reason,
        confidence=decision.confidence,
    )
