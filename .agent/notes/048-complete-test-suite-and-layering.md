# 048-complete-test-suite-and-layering.md

> 日期：2026-09-12  
> 主题：服务端测试分层落地与全 Context 测试用例补充  
> 关联规范：`docs/technical/design-server.md` §10、`AGENTS.md`

---

## 1. 背景与目标

根据 `docs/technical/design-server.md` 第十节《测试策略与目录约定》与系统 DDD 架构规范，服务端测试需摆脱单纯依赖几个大型扁平集成测试的模式，建立层次清晰、关注点解耦的测试金字塔架构：
- `unit`：聚合不变量、规则分类、状态机、纯函数；
- `application`：用例编排、门面查询、乐观锁并发防护与幂等重放；
- `integration`：Outbox 事务写入与异步消费、数据库关系与约束；
- `contract`：API ACL 权限拦截、Published Language 事件信封、AI 运行时契约；
- `support`：测试替身（Fakes）、对象工厂（Factories）与专用断言（Assertions）。

## 2. 核心成果

### 2.1 支撑层建立 (`tests/support/` + `conftest.py`)
1. **`tests/conftest.py`**：
   - 自动 mock 外部网络模型生成器 (`guard_external_ai_gateway`)，确保单元与集成测试绝不发生真实外网 LLM/VLM 调用；
   - 提供基于内存 SQLite 的独立 `db` 会话 fixture 和 `client` 测试客户端。
2. **`tests/support/factories.py`**：
   - 提供 `create_guardian`、`create_ward`、`create_task`、`create_daily_schedule`、`create_study_session`、`create_frame`、`make_learning_fact` 等工厂函数。
3. **`tests/support/fakes.py`**：
   - 提供 `FakeModelGateway`、`FakeWorkflowDispatcher`、`FakeClock`。
4. **`tests/support/assertions.py`**：
   - 提供 `assert_fact_recorded`、`assert_outbox_event_published`、`assert_fenced_outcome`、`assert_active_signal_present` 等领域专用断言。

### 2.2 领域与用例覆盖补充
1. **Behavior Analysis (`unit/behavior/`)**：
   - 验证 45° 机位下手部动作优先于桌面静止手机、空座/离座判定；
   - 滑动窗口中位数滤波、多数投票平滑单帧噪点、平局保留中心点；
   - 时序片段归并（`build_segments`）及单调时钟基准时间偏移校正（`corrected_time`）。
2. **Companion Orchestration (`unit/companion/` + `application/companion/`)**：
   - 意图路由器（`IntentRouter`）安全词绝对优先级、显式提示词、单意图流转、多意图澄清、Focus run 延续、Handoff 转移；
   - 协调器完整生命周期、Fencing 丢弃迟到 Outcome 审计记录、Command ID 幂等防篡改检测、Thread version 乐观锁版本推进与冲突拒绝。
3. **Planning & Scheduling (`unit/planning/` + `application/planning/`)**：
   - 单日总时长不超过 480 分钟强约束、新旧任务标识校验、标题与时长约束；
   - 保存草稿 -> 确认草稿 -> 正式排程与任务状态更新，确认幂等性，跨 Ward 隔离保护。
4. **Study & Tutoring (`unit/study/` + `application/study/`)**：
   - 4 级阶梯引导与 Hint Level 封顶（<=4）、直接要答案/代写强制降级与 `safety_blocked` 标记；
   - 跨学生 session 隔离保护（403）、会话关闭后禁止继续提问（409）；
   - 完整交互流转与 Outbox 事件投递。
5. **Evaluation & Reflection (`unit/evaluation/` + `application/evaluation/`)**：
   - 自评盲评隔离、复盘日期与体感状态机；
   - 自评版本（version）自增与 `self_review.submitted` 版本化事实产生；
   - 锦囊（FocusKit）采纳才发布事实；客观报告状态联动（available/pending）。
6. **Memory & Understanding (`unit/memory/` + `application/memory/`)**：
   - 事实来源四元组 `(source_type, source_id, event_type, source_version)` 幂等去重；
   - 答疑结算：必须包含 closed 且至少一条有效互动才产生 Episode；
   - Signal 候选晋升规则：必须具备至少 2 个独立 Episode 支撑且置信度达标；
   - 质疑（Challenge）立即退出画像投影，过期信号标记为 expired；
   - 门面查询（`resolve_context`）：预算分配与截断、权限范围校验、敏感信息脱敏（raw_cues）。
7. **Identity & Device (`unit/identity/` + `integration/db/` + `contract/api/`)**：
   - PBKDF2 密码加盐与防时序攻击；
   - JWT 篡改拦截、Ward session_version 单调失效保护；
   - 6 位邀请码字母表排除易混字符；
   - REST API 鉴权拦截与 401/403/404 状态码契约。
8. **Integration & Contract (`integration/outbox/` + `contract/events/` + `contract/ai/`)**：
   - Outbox 事务入库与 Worker 批量消费、状态更新（pending -> published）；
   - `LearningFactRecorded.v1` 契约信封 Schema 校验与序列化；
   - `ContextEnvelope.trace_snapshot` 脱敏审计契约、`AgentTextCandidate` 1~1200 字符限制。

### 2.3 发现并修复的代码潜在缺陷
- **`app/memory.py`**:
  在 `rebuild_long_term_profile` 中，当 Ward 初次构建画像时，内存中新实例化的 `LongTermProfile` 其 `profile_version` 为 `None`，直接执行 `+= 1` 会引发 `TypeError`。已修复为 `profile.profile_version = (profile.profile_version or 0) + 1`。

## 3. 测试验证结果
- 全量运行 `pytest tests/ -v`：
  - 用例总数：**109 passed**（由原有的 43 项扩充至 109 项，净增 66 个高质量结构化测试用例）；
  - 全绿通过，耗时约 2.6s；
  - 无任何 linter 错误。
