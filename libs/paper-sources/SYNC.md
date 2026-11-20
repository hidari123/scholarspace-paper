# 规范同步说明

本目录的 `ruff.toml` 与 `mypy.ini` 是从主仓 `packages/conventions/python/` **复制**而来。

⚠️ 子仓 CI 独立 checkout，没有主仓在场：
   - ruff 的 `extends = "./ruff.toml"` 需要本地副本
   - mypy 不支持配置继承（`extends` / `include` 都不行），只能复制

更新方式：

```bash
npx @scholarspace/cli sync --kind python
```

⚠️ 复制后请勿手改 —— 下次同步会覆盖。
