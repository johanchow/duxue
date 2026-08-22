# 一日故事 MVP：身份与模型路由

- Ward 不是 Guardian 的弱权限登录，而是绑定到单个 `ward_id` 的独立 JWT；服务端必须以 `current_ward` 校验，避免客户端隐藏按钮成为唯一权限边界。
- 家长生成 10 分钟一次性码，Ward 首次绑定后设置 4–8 位 PIN；PIN 仅存 PBKDF2 哈希。
- 模型按 `TUTORING_MODEL_NAME`、`INSIGHT_MODEL_NAME`、`GUARDIAN_STORY_MODEL_NAME` 分开配置，默认回退 `VLM_MODEL_NAME`，以便替换提供商/模型不触及业务模型或迁移。
- 验证：`duxue-server/.venv/bin/python -m unittest tests.test_e2e -v` 通过。全量 discover 目前因现有虚拟环境缺少 `pytest` 而在 `test_classifier_rules` 导入时失败。
- Flutter MVP 入口：Guardian 从 Ward 详情的「一日故事 MVP」进入，提交作业、生成 Ward 绑定码并拉取当晚事实报告；Ward 从登录页的绑定入口设置 PIN 后进入计划、伴学、自评和洞察页。验证：`flutter analyze` 与 `flutter test` 通过。
- 2026-08-22 就绪审计：RDS Alembic 版本为 `20260822_03 (head)`。但 `.env` 的 `APP_BASE_URL` 指向 `localhost:4000` 且无服务监听，未能验证运行中 API；本地 MVP 改动尚未构建/部署。伴学、归因、Guardian 建议的模型名称配置已预留，当前实现仍使用固定安全降级文案。Cam 与 Flutter release 必须分别注入 HTTPS `API_BASE_URL` / `--dart-define=API_BASE_URL=...`；release manifest 未允许 HTTP 明文流量。
