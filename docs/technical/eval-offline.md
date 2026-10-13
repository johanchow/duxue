# 读学系统 — 答疑离线评测设计

> 状态：v1 已实现（`duxue-server/evals/`），首批数据集 30 条均为 `proposed`，待人工复核 · 版本：v1.0  
> 范围：对 AI Component（首批为 `tutoring.turn`、`companion.intent`）的离线回放、判分、报告与数据集治理。  
> 关联：[AI Component 设计](infra-ai-components.md) · [Tutoring Domain](domain-tutoring.md) · [Companion 编排](domain-companion.md) · 决策笔记 `.agent/notes/117-tutoring-offline-eval.md`

## 一、目标与非目标

答疑链路的行为问题往往不是"模型不会"，而是 prompt、输出契约与出口检查叠加后在某类输入上稳定走偏：发音请求被澄清、确认句触发整轮 fallback、简单问答因多带一个字段被丢弃。这类问题改一处就可能在另一处复发，而线上只能事后从日志里发现。

目标：

- 让"已经出过的坏行为"变成可重放的数据，在换模型、改 prompt、改契约、改出口检查之前先看一眼有没有复发。
- 评测结果与线上同源：线上会触发的 fallback，评测里也触发，并带同样的原因。
- 数据集从真实对话来，经过人工复核，可审计、可脱敏、可演进。
- 诚实表达不确定性：小数据集上的差异是噪声，除非区间支持。

非目标：

- **不做 hill climbing。** 离线通过率不是优化目标，不用它排名模型或证明"变好了"。
- **不测学习效果。** 下一题正确率、认知投入依赖学生后续真实行为，离线算不出来；这些需要在合规前提下由线上指标或人工研究验证。
- 不做线上 A/B、分流、通用 override 或 `evaluation_profile` 配置协议（与 [AI Component §七](infra-ai-components.md) 一致）。
- v1 不引入 LLM judge（见 §六.4）。
- 不把评测结果当作安全放行依据：`TutorPermitPolicy`、出口检查、独立安全审核仍是唯一裁决者。

## 二、设计原则

方法取自 Khan Academy 公开论文（AIED 2026）的整理资料 `zzz/`，落到本仓库的对应关系如下：

| 原则（来源） | 本设计的落点 |
| --- | --- |
| 离线只做冒烟，不做迭代决策；核心指标测不出、数据集难维护、很快饱和 | 报告只给通过率与 Wilson 区间；区间过宽时明示"只能当冒烟"；无排行榜 |
| 数据集针对已出问题的高风险行为构造，不是随机采样；抽样 → 自动标记 → 人工复核，只留一致的 | `export` 导出并自动打 flag，人工补期望，复核后才 `confirmed`（§五.3） |
| 每条数据 = 对话历史 + 当时注入的上下文 | 一条 Case = 窗口历史 + 本轮学生句 + `context`（§五.1） |
| AI Component 是最小可测单元 | Runner 直接调组件对应的适配器，不起 HTTP、不起 Run |
| 换模型必须重跑，不能假设"至少不会更差" | 结果记录组件版本、模型、prompt 摘要、数据集哈希；`--model` / variant 便于并排 |
| "不泄露答案"与"认知参与"必须一起看 | 少量 `guard` 哨兵 Case，改发音/澄清契约时同时盯住答案保护 |
| LLM judge 有 FP/FN，必须校准并校正 | v1 只用确定性判分；将来加 judge 先有校准集（§六.4） |
| 指标三级：primary / secondary / guardrail | 同样三级（§七.1） |
| 离线数据集要去标识，且数据不外传 | 入库前脱敏；图片不入库；评测只在本机进程内运行（§五.5） |

## 三、与现有架构的关系

```mermaid
flowchart LR
    subgraph Prod[生产路径]
        W[TutoringWorkflow] --> L[tutor_loop<br/>call_tutor_model / vet_candidate]
        L --> G[QwenTutorTurnGateway]
        G --> C[components.invoke_json_component]
    end
    subgraph Eval[evals/]
        R[Runner] --> L
        R --> I[ModelIntentClassifier]
        I --> C2[complete_intent]
        C2 --> C
        D[(evals/data/*.jsonl)] --> R
        R --> S[Grader + Report]
        S --> O[(var/evals/*.json)]
    end
    X[export] -->|companion_messages 只读| D
```

- 评测**不是**第二套实现：Runner 调用与生产相同的指令构造（`build_tutor_instruction`）、有界模型循环与结构恢复（`call_tutor_model`）、越权与泄露出口检查（`vet_candidate`）。评测只替换数据库——用 Case 的 `context` 代替 `TutoringProblem`、任务标题等。
- 评测不绕过组件注册表：所有模型调用仍经 `components.invoke_json_component`。`tests/unit/ai/test_no_direct_model_calls.py` 同时扫描 `app/` 与 `evals/`。
- 评测是开发工具：位于 `duxue-server/evals/`，不进 `app/`，不挂 HTTP，不被服务进程导入。

### 生产侧为评测做的最小改动（行为不变）

| 改动 | 目的 |
| --- | --- |
| `app/application/workflows/tutor_loop.py`：`call_tutor_model`、`vet_candidate`，返回 `ModelCall` / `Vetting`（带失败原因类别，不含儿童内容） | 工作流与评测共用循环和出口检查，杜绝复制与漂移 |
| `tutor_turn.build_tutor_instruction` | 同一份指令 JSON |
| `QwenTutorTurnGateway` / `QwenLeakJudge` / `complete_intent` 增加可选 `spec`、`settings_obj` | 评测进程内换模型或 prompt；生产不传，仍用注册的组件 |

## 四、模块职责

| 模块 | 职责 |
| --- | --- |
| `evals/schema.py` | `EvalCase`、`Expect`、`Context` 等 Pydantic 模型（`extra="forbid"`） |
| `evals/dataset.py` | 加载、`validate`、脱敏 `scrub`、PII 检测、`dataset_hash`；**不导入 app**，无密钥可运行 |
| `evals/outcome.py` | 把生产出口检查的结果归为结果类别 `Observation` |
| `evals/graders.py` | 对 `Observation` 做确定性断言，返回失败原因列表 |
| `evals/runner.py` | 重建窗口与图片、重放、K 次采样、并发聚合；缺图 `skipped` |
| `evals/report.py` | Wilson 区间、三级指标、文本与 JSON 输出 |
| `evals/variants.py` | 具名候选（模型名、prompt 文本变换），仅评测进程内生效 |
| `evals/live.py` | 真实模型后端；密钥预检；评测专用 settings（绕过总开关与 env override） |
| `evals/export.py` | 从 `companion_messages` 导出待复核候选、自动 flag、脱敏、取图 |
| `evals/__main__.py` | CLI：`validate` / `run` / `export` / `compare`；导入 app 前设置 `OTEL_SDK_DISABLED=true` |

## 五、数据集

### 5.1 记录：一个决策点

JSONL，一行一条，位于 `duxue-server/evals/data/`（按组件分文件：`tutoring_turn.jsonl`、`intent.jsonl`）。

| 字段 | 含义 |
| --- | --- |
| `id` | 全局唯一，如 `turn-97103aaf-06`、`intent-b48b70b3-00`、`turn-guard-02` |
| `component` | `tutoring.turn` 或 `companion.intent` |
| `conversation_id` | 真实线程 id 前 8 位；合成用 `synthetic` |
| `turn_index` | 该线程内第几个学生句（从 0 起） |
| `history` | 本轮之前的窗口，最多 8 句（与生产 `MAX_UTTERANCES` 一致）：`author`、`text`、`images`（资源名） |
| `student_said` | 本轮学生句 |
| `images` | 本轮学生图片资源名 |
| `context` | 注入上下文：`problem`（有开放作业题时的摘要、子目标、尝试/提示次数、证据摘要）、`task_title`、`task_active`、`tutoring_intent`、`focus_agent_type` |
| `expect` | 断言，见 §六.3 |
| `tags` | 行为类别，用于分组统计，如 `pronounce`、`referent-last-reply`、`regression-fallback`、`guard` |
| `source` | `real` 或 `synthetic` |
| `flags` | 导出时的自动标记 |
| `label_status` | `confirmed` / `proposed` / `needs_decision` |
| `reviewed_by` | 复核人；仅 `confirmed` 可有 |
| `note` | 生产当时发生了什么、为什么这样标 |

**重放是单步的**：历史固定为生产记录的原文（包括当时助手那句有问题的回复），不自由续跑。这样每个决策点独立、可重复，代价是测不出多轮自愈能力（§十）。

### 5.2 标注生命周期

| 状态 | 含义 | 计入 |
| --- | --- | --- |
| `proposed` | 有人（含 AI）写了期望，尚未复核 | 单独成组报告，**不得**作为通过依据 |
| `confirmed` | 人工复核；必须有 `reviewed_by` 且期望强于"不 fallback" | primary 指标 |
| `needs_decision` | 产品/设计尚未定义正确行为 | 只记录观测，不判通过 |

规则：AI 写的标注永远是 `proposed`；`confirmed` 只由人设置；改动 `expect` 后须重新复核。`validate` 在 CI 中强制这些规则。

### 5.3 构造流程

沿用论文的四步法，针对出问题的点而不是随机抽样：

1. **抽样**：`python -m evals export --thread <id前缀>`，按学生句切分决策点；窗口选取直接复用生产的 `select_recent_utterances`。
2. **自动标记**：

   | flag | 含义 |
   | --- | --- |
   | `fallback_reply` | 助手回复是固定 `FALLBACK_TEXT` |
   | `no_reply` | 该学生句之后没有助手回复 |
   | `intent_unclear` | 助手回复是固定的场景澄清语 |
   | `clarify_reply` | 回复含编号候选（澄清） |
   | `clarify_repeat` | 连续两次澄清 |
   | `ward_repeat` | 学生重复了此前说过的话 |

   flag 只用于挑选和提示，是启发式，不是真值。
3. **补全**：人工填 `expect`、`tags`、`context`。`context` 里无法从对话还原的部分（开放作业题状态等）必须手工补；`task_active` 由回复中是否出现"回任务"提醒推断。
4. **复核**：人工确认后设 `confirmed` 与 `reviewed_by`，把行并入 `evals/data/`。导出的候选在 `var/evals/candidates/`，不入库。

### 5.4 合成哨兵（guard）

≤6 条 `source: synthetic` 的作业答案保护 Case（直接要答案、要完整解法、反复卡住、换说法套答案、发音夹带答案）。它们不是线上故障，只用于：改发音/澄清契约时，同时确认答案保护没有退化——对应论文中"优化一个指标容易误伤另一个"的教训。必须明确标注来源，不与真实 Case 混算。

### 5.5 隐私与资产

- 入库前对文本脱敏：手机号、邮箱、证件号、UUID、8 位以上长数字、指定姓名（`--name`）；`validate` 再检测一遍，并拒绝 `data:` URL、存储路径与 `http(s)://`。
- **图片永不入库**。Case 只存资源名（`img-<内容哈希前12位>.jpg|png|webp`）；文件由 `export` 复制到 `duxue-server/var/eval-assets/`（被 `.gitignore` 覆盖）。缺图的 Case 报告为 `skipped`，既不计通过也不计失败。
- 评测只在本机进程内运行，不使用第三方评测平台；调用模型走与生产相同的提供商通道。
- 评测进程强制 `OTEL_SDK_DISABLED=true`，避免把儿童文本作为 trace/log 发到观测后端。注意 `var/agent-llm-audit.jsonl` 仍可能记录评测调用。

### 5.6 演进规则

- 数据集会饱和：高通过率后区间宽到测不出提升，此时**不再往里堆会通过的 Case**，而是从新的线上故障补会失败的。
- 数据集内容变化即 `dataset_hash` 变化；哈希不同的结果不可比较。
- 首批数据集（30 条）：

  | 来源 | 内容 |
  | --- | --- |
  | 线程 `ab8f80d3`（8 条） | 鞋→shoe 直答；"这个单词怎么读" ×3（含一次 fallback、一次澄清）；澄清后的编号选择 ×3（`needs_decision`）；带词的发音（对照） |
  | 线程 `97103aaf`（7 条） | "写日记"（`needs_decision`）；成语、造句（对照）；看图问英文；"这个怎么读"、"第四句"、"是的，是的"（图片发音链） |
  | 线程 `b48b70b3`（3 条意图） | 打雷提问及两次追问（当时因意图调用 404 被固定澄清） |
  | 线程 `97103aaf`（7 条意图） | 同一线程的场景判定 |
  | synthetic（5 条） | 答案保护哨兵 |

## 六、重放与判分

### 6.1 输入重建（`tutoring.turn`）

对每次采样：

1. 由 `context.problem` 构造 `ProblemState(status="open")`，取 `TutorPermitPolicy.permit()`；无 `problem` 即无开放作业题。
2. 把 `history`/`images` 还原成模型视图：每句 `{author, text, image_urls}`，图片从 `var/eval-assets/` 读为 data URL；本轮图片同理。
3. `build_tutor_instruction` 生成与生产相同的指令（含 `history_candidates`、`permit`、`expected_act`）。
4. `TutorToolbox(db=None, …)` 提供只读工具（`get_task_context`、`get_attempt_summary`、`lookup_history`）；`context` 用 `{}`（无记忆 envelope，见 §十）。
5. `run_tutor_turn`：`call_tutor_model` → 有候选则 `vet_candidate`（`check_authority` + 事实闸门 `fact_gate` + 泄露判官，判官用生产注册的 `tutoring.leak-judge`；带图时再并行跑 `tutoring.visual-leak-judge`，图被丢弃只记原因，不算 fallback）；正文给出了答案时带“泄露：”重试一次，与生产同源。报告的 guardrail 里 `leak_retries` 是重试次数，最终仍回退的计入 fallback。

`companion.intent`：以 `ModelIntentClassifier` 包一层，捕获 `ModelGatewayError`，使"提供商错误"与"模型真的判 unclear"可区分。

### 6.2 结果类别

`outcome.classify` 把生产判定归为：

| 类别 | 来源 |
| --- | --- |
| `answer` | 候选 `act=answer` 且通过出口 |
| `hint_like` | `act=guide` 且通过出口 |
| `chat` | `act=chat` 且通过出口 |
| `clarify` | `act=clarify`（`candidates` 一并记录） |
| `redirect` | `act=redirect` |
| `pronounce` | `act=pronounce`，记录 `lesson.source_text` |
| `blocked` | `act=safety` |
| `fallback` | 无候选（提供商错误、`invalid_model_candidate`）或出口检查拒绝；附 `reason`，如 `pronounce_without_lesson`、`lesson_markup`、`segment_not_in_source`、`answer_marker`、`leak_detected`；元数据不一致（旧的 `confirm_without_solved`、`lesson_without_pronounce`、`candidates_without_clarify`）不再产生 fallback |

`fallback` 意味着学生会看到固定的 `FALLBACK_TEXT`。意图组件的结果类别是标签本身（`planning` / `tutoring` / `reflection` / `unclear`）。

### 6.3 断言（`Expect`）

| 字段 | 语义 |
| --- | --- |
| `outcome_in` | 结果类别必须属于此集合（空则不限） |
| `outcome_not_in` | 默认 `["fallback"]`：**意外 fallback 永远是失败**，除非 Case 明确允许 |
| `lesson_source_contains_any` | `pronounce` 的 `source_text` 须含其中任一（忽略大小写与空白差异） |
| `content_contains_any` | 回复正文须含其中任一 |
| `content_not_contains` | 回复正文不得含其中任何一个（用于兜住判官漏判，如作业答案字面量） |
| `visual` | `present`：孩子最终应看到图；`absent`：不应有图。针对通过全部出口检查后保留的图 |
| `visual_kind_in` | 保留的图的图型必须属于此集合（`steps`、`compare`、`segment`、`number_line`） |
| `visual_not_contains` | 保留的图的文字化描述不得含其中任何一个（兜住图泄露，如作业答案的数值） |
| `intent_in` | 仅意图 Case：标签须属于此集合；提供商错误同时判失败 |

一个样本通过，当且仅当失败原因列表为空。`confirmed` Case 必须有强于默认值的断言（`is_specific`）。

### 6.4 为什么 v1 没有 LLM judge

LLM judge 有自己的假阳/假阴率；论文也承认连自家的 Math Error judge 只有 F1≈0.61，并要求所有 judge 指标用已知误差率校正后才引用。本仓库现在没有人工校准集，所以 v1 只做确定性判分，泄露检查沿用生产判官并单独计数。若以后要加（如认知参与度、更细的泄露判定）：先建人工标注的校准集 → 报告 FPR/FNR → 校正后再引用数字 → 判官与被测模型尽量不同源（AI Component 设计已列为缺口）。

## 七、指标与报告

### 7.1 三级指标

| 级别 | 指标 | 说明 |
| --- | --- | --- |
| primary | `confirmed` Case 的通过情况，按 tag 拆分 | 采样级通过率（Wilson 区间）；**case 级**：全部采样都通过 / 不稳定 / 全部失败 |
| guardrail | fallback 率及原因分布；provider 错误数；guard Case 通过情况 | 防止"修好一处弄坏另一处" |
| secondary | p50 / p95 延迟 | 不是质量指标，用于发现成本退化 |
| secondary（表达） | `content` 字数 p50 / p95；形状 lint 违规率与规则分布；配图展示率、丢弃原因、结构通过率、触发召回与误触发率、有图与无图的延迟 | 确定性、只观测，**不设门槛**；形状 lint 与配图丢弃都不是 fallback。设计见 [答疑表达设计 §九](domain-tutoring-presentation.md) |

`proposed` 单独成组报告；`needs_decision` 只出现在结果类别分布里。

### 7.2 不确定性

- 每个 Case 采样 K 次（默认 5，温度沿用注册表）。
- 同一 Case 的样本相关，**case 级计数比采样级区间可信**；采样级区间偏乐观。
- 区间宽于 0.2、或没有 `confirmed` Case 时，报告会写明："只能当冒烟，不能据此宣称提升"。
- 两次结果的差异只有在采样数与区间都支持时才算差异；小数据集上 1~2 个 Case 的变化是噪声（首批基线中同一份代码连跑两次，样本通过率 69% → 76%）。

### 7.3 结果文件

`var/evals/<时间>-<组件>-<variant>.json`（本机，不入库）：

- `meta`：组件 ID/版本、模型、variant、prompt 摘要、K、数据集哈希、运行的 Case 数、git sha（含 `-dirty`）、时间；
- `summary`：三级指标、结果类别分布、`skipped`、提示；
- `cases`：每个样本的 `outcome`、`act`、`reason`、`error`、`passed`、`failures`、延迟、正文、`lesson_source`、候选。

`compare A B` 要求数据集哈希相同，只列出通过数变化的 Case。

## 八、实验与候选

- `--model <M>`：仅评测进程内替换模型名（`dataclasses.replace(spec)`）。
- `--variant <V>`：具名 prompt 变换。现有 `baseline` 与 `drop-no-guess-clause`（去掉窗口规则里"不要自己补一个对象"这句，用于验证它是否促使模型在指代明显时仍选择澄清）。变换目标文本已变化时会显式报错，防止静默失效。
- 原则：**一次只改一个变量**；variant 必须能被单测证明只改了预期的那一处；它们不碰注册表、不读 `AI_MODEL_OVERRIDES`。
- 采用某个候选，必须按 [AI Component §七](infra-ai-components.md) 的发布路径，做成显式、版本化的组件变更（提升版本、更新 prompt 摘要锁、补回归）。
- 需要契约改动才能做的实验（把 `act` 后置、`pending_clarification` + `resolution` 字段；`confirm` 已在 `tutor-turn.v3` 去掉）不属于 variant，应先落成具名候选实现，再用同一数据集对比。

## 九、运行与发布流程

在 `duxue-server/` 下（`PYTHONPATH=.`）：

```
python -m evals validate                                     # 校验数据集；无网络、无需密钥
python -m evals run --samples 5                              # 两个组件基线；联网
python -m evals run --component tutoring.turn --tag pronounce
python -m evals run --component tutoring.turn --model <M>
python -m evals run --component tutoring.turn --variant drop-no-guess-clause
python -m evals export --thread <id前缀> [--component companion.intent] [--name <姓名>]
python -m evals compare var/evals/<A>.json var/evals/<B>.json
```

`run` 需要 `VLM_API_KEY` / `DASHSCOPE_API_KEY`，缺失时给出明确报错；可选 `--status`、`--tag`、`--case`、`--min-pass`（`confirmed` 中全部采样通过的 Case 占比低于阈值则退出码 1，供本机脚本使用）。

**CI**：只跑无网络部分（数据集校验、判分、Runner、报告、export 的单测）。真实模型评测**不进 pytest/CI**——`conftest` 已全局禁止外部模型调用。

**通过阈值（v1）**：不设自动硬门槛。下列改动发布前必须人工跑一次并留存结果：换模型、改 `tutoring.turn` / `companion.intent` 的 prompt、改 `tutor-turn` 契约或出口检查。要求：`confirmed` 集稳定通过的 Case 数不低于上次基线，fallback 率不升，guard 不退化；落在区间内的变化一律按噪声处理。待 `confirmed` 集足够大后再收紧为自动门槛，不为小数据集固化百分比。

## 十、局限与风险

| 局限 | 影响与缓解 |
| --- | --- |
| 数据集刻意偏向出过问题的点 | 通过率不代表线上正确率，不得外推 |
| 单步重放，历史是生产记录原文 | 测不出多轮自愈；未来引入 pending 状态后需要有状态的重放 |
| `context` 无记忆 envelope | 若记忆明显影响答疑，给 Case 增加 `envelope` 字段 |
| 样本相关、Case 数少 | 以 case 级计数为准，区间仅作参考 |
| 标注者偏差（含 AI 初稿） | 只有人工复核后的 `confirmed` 才计入 primary |
| 模型随提供商静默更新 | 结果带模型名与时间；基线需要定期重跑 |
| 真实儿童文本入库 | 脱敏 + `validate` 拦截；候选与图片只在本机；复核时再看一遍 |
| 评测调用写入原文审计文件 | 调试审计时按时间区分；留存策略见 AI Component 已知缺口 |

## 十一、测试与验收

测试位于 `duxue-server/tests/unit/evals/`（文件统一前缀 `test_evals_`；该目录**不得**放 `__init__.py`，否则 pytest 会遮住顶层 `evals` 包）。

| 测试 | 覆盖 |
| --- | --- |
| `test_evals_dataset.py` | 已入库数据集合法；三条线程与 guard 均在；AI 标注不得 confirmed；confirmed 规则；PII 检测与脱敏；窗口长度；哈希稳定；CLI `validate` |
| `test_evals_grading.py` | 用 `StaticTutorModel` 重现真实故障与正常形态：闲聊接话不再回退、`progress` 无证据只是不推进、澄清代替发音、lesson 错位归位、缺 `lesson`、provider 错误、结构重试后回退、guard 与泄露判官、意图错误可见 |
| `test_evals_runner_report.py` | 采样聚合、flaky/always-fail 区分、guardrail、状态分组、小数据集提示、缺图 `skipped`、图片以 data URL 送入、指令与生产一致、variant 隔离与失效报错 |
| `test_evals_export.py` | 决策点切分、窗口 ≤8、图片资源名、flag 规则、`task_active` 推断、脱敏、仅图片不成 Case、资产内容哈希、按线程读库 |
| `tests/unit/ai/test_no_direct_model_calls.py` | `evals/` 同样不得直连提供商 |

验收：

- 评测中对受保护作业题的 `act=answer` 只按内容判定（答案标记 `answer_marker`、泄露裁判 `leak_detected`），不因 `act`/`turn` 标签本身回退，与生产一致；闲聊轮和只带无证据 `progress` 的 `guide` 不回退。
- `validate` 在无密钥环境可运行；`run` 缺密钥时报明确错误。
- 数据集无 PII、无 `data:` URL、无存储路径；`confirmed` 均有 `reviewed_by`。
- 既有答疑、组件与架构测试保持通过。

## 十二、后续（未做）

- 人工复核首批标注，提升 `confirmed` 比例。
- 用同一数据集做契约级单变量实验：`act` 后置、`pending_clarification` + `resolution`（`confirm` 语义拆分已随 `tutor-turn.v3` 落地）。
- 有状态的多步重放（引入 pending 状态后）。
- 判官型指标与校准集（泄露细判、认知参与度）。
- `confirmed` 集足够大后，把 §九 的阈值收紧为自动门槛。
