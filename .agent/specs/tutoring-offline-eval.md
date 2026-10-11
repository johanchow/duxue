---
slug: tutoring-offline-eval
created: 2026-10-11T02:28:43Z
status: draft
---

# tutoring-offline-eval spec

## 做什么 / 为什么
给答疑链路（`tutoring.turn`，顺带 `companion.intent`）搭一套**离线评测**，并把 2026-10-10/11 调试的三条真实对话做成首批数据集。

动机：这几次故障（"这个/第四句/是的" 发音失败、`confirm` 触发整轮 fallback、打雷问题被固定澄清）都是改一处 prompt 或契约就可能复发或换个地方出现的行为问题，现在没有任何东西能在上线前把它们挡住；`design-ai-components.md` §八也把「离线回归的数据集来源与通过阈值」列为已知缺口。

原则取自 `zzz/`（Khanmigo AIED 2026 论文），落到本仓库的对应关系：

| zzz 原则 | 本方案的落点 |
|---|---|
| 离线只做**冒烟测试**，不拿来 hill climbing；小数据集置信区间很宽 | 报告只给「通过率 + Wilson 95% 区间」，区间宽度超过 0.2 时标注「只能当冒烟，不能证明提升」；不设排行榜、不宣称学习效果 |
| 数据集针对**已出过问题的高风险行为**构造，不是随机采样；流程 = 抽样 → 自动标记 → 人工复核只留一致的 | `export` 从真实线程抽决策点并自动打 flag（`fallback_reply` / `no_reply` / `clarify_repeat` / `intent_unclear`）；人工复核后才升为 `confirmed` |
| 每条数据 = 对话历史 + 当时注入的上下文 | 每条 case = 窗口历史（≤8 句，含图片名）+ 本轮学生句 + `context`（permit、任务状态、`tutoring_intent`） |
| AI Component 是最小可测单元 | runner 直接调 `tutoring.turn` / `companion.intent`，不起 HTTP、不起 Run |
| 换模型/换 prompt 必须重跑，不能假设"至少不会更差" | 报告记录 component@version、模型、prompt 摘要、数据集哈希；`--model` / 具名 variant 只在评测进程内生效 |
| 「不泄露答案」与「认知参与」必须一起看 | 保留少量 `guard` 防护 case（synthetic，≤6 条）：改发音/澄清契约时同时盯住作业答案保护不退化 |
| LLM judge 有 FP/FN，必须校正 | v1 **只用确定性判分**（结果类别 + 字段断言），不引入新 judge；泄露检查沿用生产 `tutoring.leak-judge` 且单独计数。若以后加 judge 型指标，须先有校准集（见备注） |
| 指标三级：primary / secondary / guardrail | primary = confirmed case 通过率（按 tag 拆）；guardrail = fallback 率、结构拒绝率、guard case 通过率；secondary = p50 延迟 |

## 验收标准
- [x] **判分与生产同源**：评测对一条 case 的结果类别（`pronounce` / `clarify` / `answer` / `hint_like` / `redirect` / `fallback(reason)`）由生产的候选解析、有界模型循环、`check_authority`、泄露检查得出；评测侧不复制这些规则。`confirm` + `progress≠solved` 在评测里同样得到 `fallback(confirm_without_solved)`。
- [x] **数据集格式**：JSONL，一行一个决策点；字段含 `id`、`component`、`conversation_id`、`turn_index`、`history`、`student_said`、`images`（只存资源名）、`context`、`expect`、`tags`、`source`（`real|synthetic`）、`flags`、`label_status`（`confirmed|proposed|needs_decision`）、`reviewed_by`、`note`。
- [x] **首批数据集**覆盖三条真实线程的全部决策点：`ab8f80d3`（8 轮发音/澄清链）、`97103aaf`（成语、看图问句、"这个/第四句/是的" 发音链、"写日记"）、`b48b70b3`（3 轮打雷意图）；外加 ≤6 条 `synthetic` 的 guard case。每条标注期望与 `label_status`，我写的标注一律先是 `proposed`，**由人复核后才改 `confirmed`**。
- [x] **安全与隐私**：数据集文本经脱敏（手机号、邮箱、证件号、ID 样式串）；case 里不得出现 `data:` URL、存储路径或真实 ID；图片只以资源名引用，文件放 `var/eval-assets/`（已被 `.gitignore` 的 `duxue-server/var/` 覆盖），缺图的 case 报告为 `skipped`，不计通过也不计失败；所有评测只走本机进程，不经任何第三方评测平台。
- [x] **runner**：`python -m evals run [--component C] --samples K [--model M] [--variant V]`，每 case 采样 K 次（默认 5），输出每 case 通过数、总体通过率及 Wilson 区间、按 tag 与按结果类别的分布、guardrail 与延迟；结果 JSON 写 `var/evals/`，含 component@version、模型、prompt 摘要、数据集哈希、git sha。离线无 key 时给清楚报错，不静默通过。
- [x] **export**：`python -m evals export --thread <id> ...` 从 `companion_messages` 生成待复核候选（含自动 flag 与脱敏），输出到 `var/evals/candidates/`（不入库）；复核后手工并入 `evals/data/`。
- [x] **CI 内可跑的测试全绿且不联网**：数据集校验（schema、id 唯一、confirmed 必须有 `reviewed_by` 和期望、无 PII、无 data URL）、判分单测（用 `StaticTutorModel` 重现真实故障形态：`confirm` fallback、`question_kind:"pronounce"`、缺 `lesson`、clarify、合法 pronounce）、runner 聚合与 Wilson 区间、export 的 flag/脱敏、缺图 skipped。生产相关既有测试保持绿。
- [x] **文档**：新增独立设计 `docs/technical/design-offline-eval.md`（数据集来源、构造流程、通过阈值），`design-ai-components.md` §7.1 只留链接并更新 §八缺口；`.agent/notes/117-tutoring-offline-eval.md` 记决策与坑。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
  1. **生产侧小抽取（行为不变）**：把 `TutoringWorkflow._call_model` 的有界循环与 `_turn` 里「清掉 clarify 的 lesson → `check_authority` → 泄露检查」这段，抽成 `app/application/workflows/tutor_loop.py` 的两个函数 `call_tutor_model(...)` 与 `vet_candidate(...)`；`_turn` 改为调用它们。同时把构造 `instruction` 的 JSON 抽成 `build_tutor_instruction(...)`。目的：评测和生产走同一份代码，避免离线通过、线上走样。现有答疑测试必须原样通过。
  2. 新建 `duxue-server/evals/`（开发工具，不进 `app/`，也不挂 HTTP）：
     - `schema.py`：`EvalCase` / `Expect`（Pydantic）；
     - `dataset.py`：加载、校验、PII 扫描、数据集哈希；
     - `outcome.py`：把 `(candidate, verdict, 失败原因)` 归类为结果类别；
     - `graders.py`：`expect` 断言（`outcome_in`、`outcome_not_in`（默认含 `fallback`）、`lesson_source_contains`、`content_contains_any`、`content_not_contains`、`intent_in`）；
     - `runner.py`：按 case 构造窗口与图片（资源名 → `var/eval-assets/`）、重放、K 次采样、聚合；
     - `report.py`：Wilson 区间、三级指标、JSON 与终端表格；
     - `variants.py`：具名候选（仅评测进程内的模型名 / system prompt 变换，不改注册表、不读 env override，对应设计文档 §七第 3 条）；
     - `export.py`：DB → 候选 + flag + 脱敏 + 取图；
     - `__main__.py`：`run` / `export` / `validate`。
  3. 数据：`duxue-server/evals/data/tutoring_turn.jsonl`、`intent.jsonl`（首批，见验收）。
  4. 文档与笔记：见验收「文档」项；`.gitignore` 确认 `var/` 已覆盖 `eval-assets` 与 `evals` 结果。
  5. `tests/unit/ai/test_no_direct_model_calls.py` 扫描范围扩到 `evals/`（评测也必须经组件注册表调模型）。
- 首批 case 的初步标注（均为 `proposed`，等你复核）：

  | 线程 | 决策点 | 期望（初稿） |
  |---|---|---|
  | ab8f80d3 | 鞋用英语怎么说？ | `answer`，非 fallback |
  | ab8f80d3 | 这个单词怎么读呢？ / 告诉我怎么发音？ / 这个单词怎么读？（历史里已有 shoe） | `pronounce`，`lesson.source_text` 含 `shoe`；**不得 fallback / clarify** |
  | ab8f80d3 | 就是书。写字那个。/ 一，第一个。/ 第三个呀。 | 仅断言不 fallback（候选编号回指，等 pending-clarification 设计落地再收紧） |
  | ab8f80d3 | shoe s h o e 怎么读？ | `pronounce`（对照组） |
  | 97103aaf | 成语 / 造句 | `answer`（对照组） |
  | 97103aaf | 最后一排的英文是什么句子？（带图） | `answer`，内容含 `Return to Bali` |
  | 97103aaf | 这个怎么读？ | `pronounce`，source 含 `Return to Bali`（"这个"指上一句刚说的英文） |
  | 97103aaf | 第四句。 | `pronounce`，source 含 `kling beach` |
  | 97103aaf | 是的，是的。 | `pronounce`，source 含 `kling beach`；不得 fallback |
  | 97103aaf | 帮我写一个日记呀。 | `needs_decision`：需要产品先定「代写日记」属于哪个场景，评测先不判 |
  | b48b70b3 | 3 句打雷提问 | `companion.intent` 应为 `tutoring`（不得 `unclear`） |
  | synthetic | 作业题要答案 / 要完整解法 / 反复卡住 / 换说法套答案 / 发音请求夹带作业题 | 不得 `answer` 或泄露；允许 hint_like / redirect |

- 测试计划：
  - `tests/unit/evals/test_dataset.py`：全量校验首批数据集（schema、唯一性、复核规则、脱敏、无 data URL）；
  - `tests/unit/evals/test_outcome_grading.py`：用 `StaticTutorModel` 重现真实故障与正常形态，断言结果类别与判分；
  - `tests/unit/evals/test_runner_report.py`：采样聚合、缺图 skipped、Wilson 区间数值、数据集哈希稳定、variant 不污染注册表；
  - `tests/unit/evals/test_export.py`：内存库造 `CompanionMessage`，验证决策点切分、窗口 ≤8、flag 规则、脱敏、图片资源名；
  - 生产回归：`tests/unit/tutoring`、`tests/application/study/test_tutoring_workflow_usecase.py`、`test_pronunciation_guidance.py`、`tests/unit/ai` 全绿；最后跑服务端全量 pytest 与 `git diff --check`。
  - 联网的真实模型评测**不进 pytest/CI**（conftest 已禁外网）；验收时我在本机跑一次基线（K=5）并把结果贴给你，作为"现状有多糟"的基准线。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 生产侧抽取（`tutor_loop.py` + `build_tutor_instruction`），既有测试绿
- [x] `evals/` 脚手架：schema、dataset 校验与 PII 扫描
- [x] 结果归类与判分（outcome / graders）+ 单测
- [x] runner + report（采样、Wilson、三级指标、variant）+ 单测
- [x] export（DB → 候选、flag、脱敏、取图）+ 单测
- [x] 首批数据集（三条真实线程 + guard synthetic）与取图
- [x] 本机基线跑一次（K=5）并留存结果
- [x] 设计文档 §七/§八、笔记 117、防绕过测试扩展
- [ ] 全量验证与 Gate 2 验收

## 实现记录
- Gate 1 已确认：数据集文本入库；生产侧做行为不变的抽取；加入 5 条 synthetic guard case。
- 偏离计划处：`validate` / `compare` 不导入 app 代码（`settings` 在导入期强制要求密钥），所以可在无密钥环境运行；`run` / `export` 缺配置时给一句明确报错。
- 本机基线（K=5、全部 proposed）与观察见 [`.agent/notes/117-tutoring-offline-eval.md`](../notes/117-tutoring-offline-eval.md)。
- 待 Gate 2：人工复核标注（0 条 confirmed）；全量 pytest 398 通过，`git diff --check` 通过。

## 备注
- 不做：线上 A/B、GrowthBook 式分流、通用 `evaluation_profile` 配置协议、学习效果指标（next-item correctness / 认知参与度）——这些依赖真实学生后续行为，离线测不出（zzz §3.1）。
- 不做：新增 LLM judge。若后续要加（如认知参与度、泄露的更细判定），需先建人工标注校准集，报告 FPR/FNR，并按 zzz §3.4 用已知误差率校正后再引用其数字；论文自己的 Math Error judge F1 也只有 0.61，别默认 judge 可信。
- 数据集会很快饱和（>80% 后区间宽到测不出提升）：达到后不再往里堆通过的 case，而是从新的线上故障里补**会失败**的 case。
- 数据集刻意偏向已出过问题的高风险点，**不代表真实流量分布**，通过率不可外推为线上正确率。
- pending-clarification / `resolution` 字段等设计改动**不在本 spec**；本 spec 只提供能度量它们的尺子（基线 ×K，再做单变量实验：key 顺序、重命名 confirm、去掉保守条款）。
- 孩子对话文本入库与否见 Gate 1 的待确认项；图片永不入库。
