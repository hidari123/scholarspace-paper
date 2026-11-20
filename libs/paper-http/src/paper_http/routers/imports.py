"""导入路由 —— 从数据源拉取论文入库."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status
from paper_core.application.ports import SearchQuery

from paper_http.schemas import ImportReportResponse, ImportRequest
from paper_http.service import UnsupportedSourceError

__all__ = ["router", "set_service"]

router = APIRouter(prefix="/api/v1/papers", tags=["imports"])

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


@router.post("/import", response_model=ImportReportResponse)
async def import_papers_endpoint(payload: ImportRequest) -> ImportReportResponse:
    """从数据源导入论文.

    ⚠️ **返回报告** —— 用户要知道实际入库了几条。

    Raises:
        HTTPException: 数据源不支持（422）/ 外部源失败（502）
    """
    query = SearchQuery(query=payload.query, limit=payload.limit)

    # ⚠️ **取服务要在 try 外面** ——
    # `_svc()` 抛的 HTTPException(503) 会被下面的
    # `except Exception` 捕获，变成 502 —— 语义错了。
    service = _svc()

    try:
        report = await service.import_from_source(payload.source, query)
    except UnsupportedSourceError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except Exception as error:
        # ⚠️ **外部源挂了 → 502** —— 不是我们的锅
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"数据源请求失败：{error}",
        ) from error

    return ImportReportResponse(
        fetched=report.fetched,
        inserted=report.inserted,
        updated=report.updated,
        skipped=report.skipped,
        details=list(report.details),
    )
