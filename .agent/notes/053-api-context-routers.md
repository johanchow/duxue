# API 按 Context 拆分

> 日期：2026-09-14
> 关联规范：`.agent/specs/split-api-context-routers.md`

## 决策

- `app/api/router.py` 只汇总并注册 v1 Context routers；FastAPI app 的创建仍只属于 `bootstrap/app.py`。
- 路由按 Interface 责任拆成 `system`、`identity`、`device_ingestion`、`planning`、`study`、`evaluation`、`memory`、`companion`、`behavior`。一个 path/method 只能在一个 router 中注册。
- 旧单体文件中的共享 HTTP 辅助函数移入 `v1/common.py`。该模块不定义 router，也不反向导入具体 router；尤其计划查询需要的 active-session 视图由 common helper 提供，避免 Planning 与 Study interface 层互相导入。
- 这次仅移动 endpoint 和依赖声明；实际业务编排与持久化行为不变。测试中的 mock patch 路径改为 endpoint 所属 router。

## 验证

- 迁移前后 OpenAPI 的 path + HTTP method JSON 完全相同。
- `ENV_FILE=.env.test .venv/bin/pytest tests -q`：127 passed。
