---
slug: unify-ai-component-gateway
created: 2026-10-10T00:00:00Z
status: done
---

# unify-ai-component-gateway spec

## 做什么 / 为什么

将服务端模型调用的第一阶段统一为 Python 类型化的 Gateway：集中注册 `ComponentSpec`，通过统一 `invoke()` 完成调用、结构解析、遥测和原文审计，并为场景路由、答疑主调用、答案泄露 Judge 建立离线回归。该阶段不引入 YAML、通用 override、A/B 分流或可替换 Workflow。

## 验收标准

- [x] `ComponentSpec` 是 Python dataclass，包含稳定组件 ID、不可变版本、模型、系统提示、生成参数与输入/输出契约；Registry 是集中、显式的 Python 注册表。
- [x] Gateway 通过同一 `invoke()` 路径执行 P0 组件，统一记录组件 ID/版本、模型、token、耗时、provider request ID、结构错误与 fallback 所需错误分类；不将儿童原文、图片 data URL、密钥或 CoT 写入普通 trace/log。
- [x] `companion.intent`、`tutoring.turn`、`tutoring.leak_judge` 三个现有调用点迁移到组件注册表，既有的输出契约、受保护场景 fail-closed 和 fallback 行为不变。
- [x] 为上述三个组件增加无网络离线回归测试，覆盖组件身份/版本、结构化成功结果与非法输出/提供商失败的既有保守行为。
- [x] `docs/technical/design-ai-components.md` 收敛为两阶段方案：第一阶段是类型化 Gateway；只有出现真实灰度需求才考虑具名候选版本，且不承诺通用 override。
- [x] Phase 2：Registry 成为全部文本类 LLM 调用的唯一总表；`ComponentSpec` 含默认 `model`、`risk_tier`、prompt 引用、输入/输出契约；prompt 正文集中在 `prompts.py`，带摘要版本锁。
- [x] `tutoring.turn` / `tutoring.leak-judge` 为 `protected`，不可被环境变量覆盖；`AI_MODEL_OVERRIDES` 仅按组件覆盖 `standard` 模型名，非法值启动即失败，Trace 带 `model_source`。
- [x] `QwenAgentModelGateway`、`task_intake`、`plan_intake` 迁入 Registry；防绕过测试保证 `app/` 内只有 `components.py`/`client.py` 与待迁的 VLM `inference.py` 直连 SDK。
- [x] 受影响服务端测试全绿，`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）

- 影响文件：
  1. `docs/technical/design-ai-components.md`：移除 YAML、签名包、通用 override 与可替换 Workflow，改为 Python Registry / 两阶段演进。
  2. `duxue-server/app/infrastructure/ai/components.py`（新增）：定义 `ComponentSpec`、P0 组件 Registry 与只读查询接口。
  3. `duxue-server/app/infrastructure/ai/model_gateway.py`、`tutor_turn_model.py`、`intent_classifier.py`：收敛直接模型调用到共享 invoke helper，同时保持调用方的特定输出类型和结构恢复语义。
  4. `duxue-server/app/infrastructure/observability/telemetry.py`：按现有安全审计约束为组件标识补充低基数 trace 属性（仅在现有 API 足以支持时修改）。
  5. `duxue-server/tests/infrastructure/ai/`（新增或现有相邻测试）：无网络 unit/offline 回归，覆盖三个 P0 组件和统一调用行为。
  6. `.agent/notes/116-declarative-ai-components-design.md`：记录最终收敛的边界和实施结果。
- 测试计划：
  - 先写组件 Registry 与统一 invoke 的 unit test，使用 fake client，断言模型请求、结构解析、遥测元数据和异常分类。
  - 为 intent、tutor turn、leak judge 写离线 fixtures，验证成功 JSON 与非法 JSON / provider failure 走原有保守行为。
  - 运行相应测试文件，再运行 `duxue-server` 全量 pytest；最后执行 `git diff --check`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）

- [x] 收敛设计文档与决策笔记
- [x] 建立类型化 ComponentSpec、Registry 与共享 invoke
- [x] 迁移 P0 三个调用点并保持兼容
- [x] 增加离线回归测试
- [x] Phase 2：错误类型拆出 `errors.py`；新增 `prompts.py`；Spec 去掉 `model_setting` 槽位；删除 `TUTORING_/PLANNING_/INSIGHT_/GUARDIAN_STORY_MODEL_NAME`、`TASK_INTAKE_MODEL`；迁移三处调用；新增 Registry/覆盖/prompt 锁/防绕过测试
- [x] 全量验证：`pytest tests -q` 333 passed；`git diff --check` 干净
- [x] 模型分配：turn/intake→qwen3-vl-plus，Judge/advice→qwen-plus，路由→qwen-flash（纯文本不发图），reply→qwen3-vl-flash；新增 `accepts_images`、`timeout_seconds`；测试 336 passed
- [x] Gate 2 验收（用户确认提交）

## 备注

- ComponentSpec 不拥有领域 Policy、ACL、ContextBuilder、Workflow 控制流或 Domain 写入。
- 配置随 Python 代码发布；不引入 YAML、远程配置、签名发布包、点号路径覆盖或实验分流。
- 未来如确有灰度需求，只考虑显式具名候选版本和 shadow 执行，须另立 spec 决定分流与评测边界。
- Phase 2 范围外（另立 spec）：VLM 帧分析（批处理 + 实时 + 并发/成本约束）、答疑流式、Judge 与 Generator 强制不同源、成本归集、provider 回退链、原文审计通道、离线回归数据集与阈值。
- 模型名 `qwen-flash` / `qwen-plus` / `qwen3-vl-plus` 经百炼文档核对仍可用（`qwen-*` 归在"旧版"，另有 qwen3.7/3.8 新代际，原生多模态）；未在你的账号上做过实际调用，上线前先各调一次。
- 行为变化：路由与复盘不再发送图片；intake 超时由（原 SDK 默认）改为 60s；答疑升到 vl-plus 会提高单价与延迟，需观察首字延迟。
- 部署注意：被删除的 `*_MODEL_NAME` / `TASK_INTAKE_MODEL` 环境变量不再生效，默认全部为 `qwen3-vl-flash`；若线上曾设置不同值，需写入 Registry（或对 standard 组件用 `AI_MODEL_OVERRIDES`）。
- 顺带修复：`tests/test_e2e.py::…pause_and_complete…` 在 HEAD 即失败，原因是断言过时（完成的 Task 按 domain-planning 会离开任务池），已改为 `assertNotIn`。
- 验证记录（2026-10-10，Phase 1）：P0 回归 34 passed；服务端全量 `pytest tests -q` 为 314 passed / 1 failed。失败可独立复现于 `tests/test_e2e.py::EndToEndTest::test_ward_can_pause_and_complete_planned_or_unplanned_tasks`，断言完成后的任务仍在任务池；该路径不触发模型调用，且属于本 feature 范围外，尚未处理。
