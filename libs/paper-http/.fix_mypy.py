"""修 paper-http 的 mypy —— 仓储是 Any，要显式标注。"""

from pathlib import Path

BASE = Path(r"C:\work\scholarspace-paper\libs\paper-http\src\paper_http")

# ── ① service.py ─────────────────────────────────────
path = BASE / "service.py"
text = path.read_text(encoding="utf-8")

old = """        paper = await self._repository.get(paper_id)
        if paper is None:
            raise PaperNotFoundError(f"论文不存在：{paper_id}")

        return paper"""
new = """        # ⚠️ **显式标注类型** —— 仓储是 `Any`（端口注入）
        paper: Paper | None = await self._repository.get(paper_id)
        if paper is None:
            raise PaperNotFoundError(f"论文不存在：{paper_id}")

        return paper"""
assert old in text, "A: get not found"
text = text.replace(old, new)

old = """        return await self._repository.delete(paper_id)"""
new = """        deleted: bool = await self._repository.delete(paper_id)
        return deleted"""
assert old in text, "B: delete not found"
text = text.replace(old, new)

path.write_text(text, encoding="utf-8", newline="\n")
print("service.py: annotations added")

# ── ② routers/papers.py ──────────────────────────────
path = BASE / "routers" / "papers.py"
text = path.read_text(encoding="utf-8")

old = """    try:
        return await _svc().get_full_text(paper_id)
    except PaperNotFoundError as error:"""
new = """    try:
        full_text: str = await _svc().get_full_text(paper_id)
    except PaperNotFoundError as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error

    return full_text

    # ⚠️ **下面这段永远不会执行** —— 留着提醒自己
    #    上面的 except 已经处理了 NotFound。
    try:
        pass
    except PaperNotFoundError as error:"""
assert old in text, "C: full text not found"
text = text.replace(old, new)

path.write_text(text, encoding="utf-8", newline="\n")
print("papers.py: annotation added")
