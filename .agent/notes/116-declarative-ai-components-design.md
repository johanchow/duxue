# 声明式 AI Component 设计

日期：2026-10-10

- 决策：第一阶段采用 Python `ComponentSpec` + 集中 Registry + 统一 `invoke_json_component()`；不引入 YAML、签名发布包、远程配置、通用 override 或可替换 Workflow。配置、prompt 与测试随代码发布。
- 已实现 P0：`companion.intent@v1`、`tutoring.turn@v1`、`tutoring.leak-judge@v1` 均经统一 Gateway 执行，Trace 记录组件 ID/版本、模型、token、时延与 provider request ID；现有输出 Schema、结构恢复和 fallback 由调用方继续拥有。
- 边界：组件机制不替代领域代码。ACL、`TutorPermitPolicy`、答案保护、独立安全审核、输出 Validator、Companion Run fence、事实/Outbox、事务与删除策略不属于 `ComponentSpec`。
- 后续：只有出现真实灰度需求，才另立设计评估具名候选版本与 shadow；不预设通用 override 或 A/B 平台。

旧组件设计文档已移除；现行实现见 [`components.py`](../../duxue-server/app/infrastructure/ai/components.py)，目标结构见 [`design-agent.md`](../../docs/technical/design-agent.md)。

## Phase 2（2026-10-11）

- 模型名属于行为，写进 Registry 评审；端点/密钥/超时/总开关留环境变量。环境变量只保留 `AI_MODEL_OVERRIDES` 这个按组件 ID 的应急覆盖，且 `protected`（`tutoring.*`）禁止覆盖，非法值启动失败，Trace 带 `ai.model_source`。
- `prompt_id` 以前是空引用：现在 Spec 持有 `PromptTemplate` / `DynamicPrompt` 对象，`prompts.py` 摘要锁（`tests/unit/ai/test_prompt_lock.py`）保证改正文必须升版本。动态 prompt（intake）渲染函数留在原模块，以 `module:function` 注册并按源码计摘要。
- 防绕过测试（`test_no_direct_model_calls.py`）是“全部收口”能长期成立的唯一保证；新增 LLM 调用必须先注册组件。
- 坑：`conftest` 自动 patch 了 `QwenAgentModelGateway.generate` 与 `components.invoke_json_component`，测它们本身时要在模块导入期保存真实引用；`settings` 是 frozen dataclass，测试用 `monkeypatch.setattr(components, "settings", SimpleNamespace(...))`。
- 未做：VLM 帧分析、流式、Judge/Generator 不同源强制、成本归集、provider 回退、原文审计通道、回归数据集阈值。

## 模型分配（2026-10-11）

- 当前模型分配以 `components.py` 和 `test_model_assignment_matrix` 为准。纯文本组件由 Gateway 把图片 part 换成占位文字（`accepts_images=False`），避免提供商拒绝。
- 未验证：账号上的实际可用性、延迟、单价；答疑 vl-plus 的首字延迟是否仍满足 P90<1.2s（当前非流式，本就不满足，需流式后复测）。
- 候选：qwen3.7/3.8 原生多模态代际；决策模型 `decision-model-preview`（路由/Judge，需新增 `decision` 调用形态与红队集）。
