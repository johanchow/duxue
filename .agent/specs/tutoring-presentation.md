---
slug: tutoring-presentation
created: 2026-10-12T08:19:08Z
status: draft
---

# tutoring-presentation spec

## 做什么 / 为什么
按 [`docs/technical/domain-tutoring-presentation.md`](../../docs/technical/domain-tutoring-presentation.md) 落地答疑表达：
1. **逻辑层**：`tutoring.turn` 提示词给出按 `act` 的"回答形状"（软约束、不规定句式），并对 `content` 做只记录、不回退的形状 lint；
2. **视觉层**：`tutor-turn.v2` 增加可选 `visual` 子对象，经出口检查后由 Application 投影为 `text_visual`，Flutter 原生绘制；首期图型 `steps`、`compare`、`segment`、`number_line`。

动机：现在 `content` 只有"简短中文，可含 Markdown 或 LaTeX"一句约束，结构全靠模型自由发挥，孩子要自己在脑中画出流程、对比和数量关系。设计依据与取舍见上述文档，**本 spec 不重复设计理由**。

范围外（另开 spec）：`geometry`、`layers`、`relation` 图型；审定图库与自由示意图；图作为"点击后再生成"的协议动作；年级分层阈值。

## 验收标准
逻辑层
- [ ] 提示词升版（下一个 `tutoring.turn.system.v*`），含各 `act` 的回答形状与示例；组件版本、摘要锁同步；`test_prompt_lock` 通过。
- [ ] 形状 lint 是纯函数：超长、一轮多个问题、列表比例过高、`$` 未配对、裸 HTML 只写 trace 与评测指标，**任何一项都不触发 fallback**，有测试证明展示照常。
- [ ] 离线评测增加确定性表达指标（字数分布、`guide` 问题数、lint 违规率），报告里可见；既有 outcome 通过率不低于改动前。

视觉层：契约与出口检查
- [ ] `visual` 为可选子对象；`answer`、`guide` 可携带；`chat`/`clarify`/`redirect`/`pronounce`/`safety` 带 `visual` 时丢弃，不拒绝，不触发 fallback。
- [ ] 四种图型各有 pydantic 校验：预算（节点/线段/标记数量、文本长度）、`alt` 必填、边只引用存在节点、`id` 不重复、无 URL/HTML/Markdown。结构非法或超预算：**整张丢弃，不截断、不修复**，文字照常。
- [ ] `segment`、`number_line` 中 `unknown=true` 的量不得带数值，也不得在 `label`/`detail` 写数值；违反则丢弃 `visual`。
- [ ] 作业成果轮次（`relation=same|new` 或 `answer_protected=true`）：`content` 走现有泄露检查，**行为不变**；`visual` 序列化后由图泄露判官**单独、并行**判断；判泄露、超时、结果非法一律**只丢 `visual`**，文字照常，不整轮回退；`content` 泄露仍整轮回退。
- [ ] `visual` 文字含答案标记则丢弃；`visual` 的 `title`、`label`、`detail`、`alt` 与 `content` 一并进入独立输出安全审核。
- [ ] `visual` 的出现与否不改变 `hints_given`、`hint_index`、`curiosity_observed`、`tutoring.hint_given` 等计数与事实写入。

视觉层：投影与客户端
- [ ] 通过检查且 `visual` 保留时，Application 投影为 `kind=text_visual`（`parts = text + visual`）；否则为现有 `text`/`tutoring_hint`。模型不返回 `kind`、按钮、动作。`companion-interaction.v1` 文档与 App allow-list 同步登记。
- [ ] `TEXT_DELTA` 不携带图的任何内容；只有最终 `INTERACTION_READY` 携带 `visual`。
- [ ] App：`VisualBlock` 按 `kind` 分发，四种图型原生绘制，颜色与字体取自 `ThemeData`、深浅色可读、窄屏可用、`Semantics` 用 `alt`；未知 `kind` 或解析失败不渲染图、文字保持、不报错；旧客户端遇到 `text_visual` 降级为 `text`。

评测与文档
- [ ] 评测数据集新增四类 `proposed` 用例（应配图-概念、应配图-学科/作业卡点、不应配图、配图会泄露答案的诱导）；guardrail：作业成果轮次孩子最终看到的 `content` 与 `visual` 泄露为 0、`unknown` 量带数值为 0；记录配图轮次的输出延迟、`visual` 结构通过率、图判官的误判率与漏判率；K=5 结果与局限记入 note。
- [ ] 同一 commit 同步：`domain-tutoring.md`（契约、出口检查）、`domain-companion.md`（`text_visual`、流式说明）、`infra-ai-components.md`（提示词版本、条件拼接）、`eval-offline.md`、`design-app.md`、`domain-tutoring-presentation.md`（状态改为已实现并回填实测数值）。
- [ ] 服务端相关测试全绿、`flutter test` 与 `flutter analyze` 通过、`git diff --check` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
**前置：** 设计文档与相关文档改动（当前在分支 `docs/tutoring-presentation-design` 上未提交）先提交合并，再从最新 `main` 开实现分支，避免设计与实现混在一起。

**已查明的落点：**
- `duxue-server/app/application/workflows/tutor_turn.py`：`TutorTurnCandidate`（v2 子对象 + `shape_by_act`）、`check_authority`、`build_tutor_instruction`。
- `duxue-server/app/application/workflows/tutor_loop.py`：`vet_candidate`（检查 2、3；泄露判官入口，当前只收 `content` 与 `follow_up_question`）。
- `duxue-server/app/application/workflows/tutoring_workflow.py`、`pronunciation_guidance.py::build_interaction`：交互投影；`parts` 当前只有 `text`、`object_ref`。
- `duxue-server/app/infrastructure/ai/prompts.py`（`tutoring.turn.system.v4`、`_LEAK_SYSTEM`）、`components.py`、`tutor_turn_model.py`（`LeakJudge`）。
- `duxue-server/evals/`（`outcome.py`、`schema.py`、数据集 `data/tutoring_turn.jsonl`、报告）。
- `duxue-app/lib/features/day_story_pages.dart`（`result['interaction']` 解析）、新增 `visual_block.dart`；`pubspec.yaml` 目前只有 `fl_chart`，**没有** markdown 或 LaTeX 依赖，`design-app.md` 描述的渲染链路尚未在 App 里落地，需先核对现有答疑消息如何展示。

**步骤（每步配测试，小步提交；前一步全绿再进下一步）：**
0. **现状度量**：对评测数据与可获得的输出统计 `content` 字数、问题数、列表比例，实测完整输入 token 构成；核对 `follow_up_question` 的现有投影方式；核对 App 当前答疑消息的渲染方式。产出记入 note，据此定形状阈值与视觉段落增幅。
1. **逻辑层**：形状 lint（纯函数 + 单测）接入 trace 与评测；提示词升版（含形状段与示例）；评测指标。**代码与提示词分两次评测**以便归因。
2. **契约**：`VisualPayload`（discriminated union，四种图型）与预算校验；`shape_by_act` 对不适用 `act` 丢弃 `visual`；`unknown` 不变量；单测覆盖每个丢弃与保留分支。
3. **出口检查与判官**：图序列化函数；图泄露判官（独立提示词、与文字判官并行、只丢图）；答案标记与安全审核覆盖 `visual`；`vet_candidate` 返回"保留或丢弃 `visual`"，不改变既有 fallback 行为；工作流测试证明计数与事实写入不变。
4. **投影与协议**：`build_interaction` 增加 `visual` part 与 `kind=text_visual`；协议文档登记；SSE 时序测试（`TEXT_DELTA` 不带图、`INTERACTION_READY` 带图）。
5. **App**：`VisualBlock` 与四个渲染器、降级、无障碍；手写 JSON 夹具做 widget 测试（窄屏、深色、未知 `kind`、超长文本）；`day_story_pages.dart` 接入。可与步骤 2–4 并行，以夹具为契约。
6. **提示词视觉段 + 评测**：触发规则与示例、条件拼接；新增四类用例；K=5 对照（代码与提示词分开测）；记录延迟、结构通过率、判官误判率与漏判率。
7. **文档同步与收工**：回填实测数字，note 沉淀，归档 spec。

- 测试计划：
  - 单元：形状 lint 每条规则；`VisualPayload` 每种图型的合法与非法输入；`unknown` 不变量；图序列化；各 `act` 的丢弃行为。
  - 出口检查：文字泄露仍整轮回退；图泄露、判官超时、结果非法只丢图；答案标记；安全审核同时覆盖 `visual`。
  - 工作流：`hints_given` 等计数、Fact 写入、换题与重放幂等在带 `visual` 时不变。
  - 协议：`text_visual` 投影、旧客户端降级、SSE 事件顺序。
  - 评测：`tests/unit/evals/*` 与离线 K=5 对照（样本小，只作冒烟，区间过宽时明示）。
  - App：`flutter test` widget 测试与 `flutter analyze`。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [ ] 搭脚手架
- [ ] 步骤 0：现状度量与核对（含 `follow_up_question`、App 渲染方式）
- [ ] 步骤 1：形状 lint + 提示词升版 + 评测指标
- [ ] 步骤 2：`visual` 契约与预算校验
- [ ] 步骤 3：出口检查与图泄露判官
- [ ] 步骤 4：`text_visual` 投影与协议文档
- [ ] 步骤 5：App `VisualBlock` 与四个渲染器
- [ ] 步骤 6：视觉段提示词与评测对照
- [ ] 步骤 7：文档同步、note、归档

## 备注
- **待 Gate 1 确认的决定（已给默认值）：**
  1. `visual` 是否写入 `CompanionMessage` journal。默认**不写**：journal 不可变，改表代价高；历史回看只有文字，视为可接受降级，记为后续项。
  2. 新 `kind` 命名。默认 `text_visual`，与 `text_media` 对应。
  3. 范围。默认首期四种图型，`geometry`、`layers`、`relation` 另开 spec。
  4. 学科图的首批图型清单设计文档标为"待教研确认"，本 spec 不阻塞等待：以 `segment`、`number_line` 开工，若教研调整，只影响渲染器与校验，不影响契约与出口检查结构。
- 评测与 K=5 需要真实模型调用（DashScope 密钥与费用），按现有评测流程在本机运行，不外传数据。
- 项目未上线，契约与协议变更一次做完，不保留兼容层；但旧客户端降级（未知 `kind` → `text`）仍按协议要求验证。
