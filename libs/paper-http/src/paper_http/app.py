"""FastAPI 应用工厂.

⚠️ 用**工厂函数**而不是模块级 app 实例 ——
测试时可以建多个隔离的实例。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI

from paper_http.routers import imports, papers

__all__ = ["create_app"]


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """生命周期钩子.

    ⚠️ 生产环境在这里初始化数据库连接、HTTP 客户端。
    """
    del app  # ⚠️ 显式标记未使用 —— 避免 ARG001
    yield


def create_app(
    service: Any = None,
    **kwargs: Any,
) -> FastAPI:
    """创建 FastAPI 应用.

    :param service: 论文服务（注入到路由）
    :param kwargs: 传给 FastAPI 构造函数的参数
    :return: 应用实例
    """
    app = FastAPI(
        title="scholarspace-paper",
        description="scholarspace 论文检索与文献库",
        version="0.1.0",
        lifespan=_lifespan,
        **kwargs,
    )

    app.include_router(papers.router)
    app.include_router(imports.router)

    # ⚠️ **总是设置**（包括 None）——
    #    只在传了值时才设的话，上一个 app 留下的依赖会**泄漏到下一个 app**。
    papers.set_service(service)
    imports.set_service(service)

    @app.get("/health")
    async def health() -> dict[str, str]:
        """健康检查。"""
        return {"status": "ok"}

    return app
