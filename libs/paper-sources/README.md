# paper-sources

scholarspace 论文数据源适配器。

见 `../../README.md`。

## 数据源

| 适配器 | API | 格式 | 备注 |
|---|---|---|---|
| `ArxivSource` | `export.arxiv.org/api/query` | **Atom XML** | 必须带 User-Agent，否则被封 |
| `CrossrefSource` | `api.crossref.org/works` | JSON | 必须带 mailto（进礼貌池）|

⚠️ **两个源的检索语法完全不同** ——
arXiv 用 `ti:` / `au:` / `all:` 前缀，
Crossref 用 `query.bibliographic` / `query.author` / `filter=`。

⚠️ **都实现 `PaperSourcePort`** —— 上层代码不用区分数据源。
