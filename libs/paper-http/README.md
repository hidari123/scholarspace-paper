# paper-http

论文检索与文献库的 **HTTP 接口层** —— FastAPI 路由。

见 `../../README.md`。

## 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/papers/search` | 检索（本地库 + 可选外部源）|
| GET | `/api/v1/papers/{id}` | 取论文 |
| GET | `/api/v1/papers/{id}/full-text` | 取全文 |
| GET | `/api/v1/papers/{id}/duplicate/{candidate_id}` | 查重 |
| DELETE | `/api/v1/papers/{id}` | 删除（幂等）|
| POST | `/api/v1/papers/import` | 从数据源导入 |

## 为什么检索是 POST

⚠️ 检索条件太复杂（作者 + 期刊 + 关键词 + 年份区间 + 开放获取 + 分页），
GET 的 query string 装不下。

⚠️ **外部源的检索结果不会入库** —— 只是临时展示，
用户点了「收藏」才入库。
