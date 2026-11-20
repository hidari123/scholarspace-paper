# paper-core

scholarspace 论文领域模型 —— 文献库的核心。

见 `../../README.md`。

## 职责

| 模块 | 内容 |
|---|---|
| `domain/value_objects.py` | `Paper` / `Author` / `Institution` / `Citation` / 各种枚举 |
| `domain/entities.py` | 实体 + `Paper.from_source()` |
| `application/ports.py` | `PaperRepositoryPort` / `PaperSourcePort` / `SearchQuery` |
| `application/dedup.py` | **去重服务**（DOI → arXiv → 标题+作者+年份）|
| `application/import_service.py` | 导入服务（拉取 → 去重 → 合并入库）|
| `infrastructure/memory.py` | 内存实现（开发与测试）|

## 零外部依赖

⚠️ `paper-core` **只依赖标准库** —— 领域层不该被第三方库绑住。
