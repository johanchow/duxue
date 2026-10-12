# 121 答疑表达：回答形状 + 可选配图（首期）

日期：2026-10-12

事实源：`docs/technical/domain-tutoring-presentation.md`（含 §十四 实现状态与偏差）；spec 见 `.agent/specs/tutoring-presentation.md`。

- 做了什么：`tutoring.turn@v5`（回答形状段 + 可选 `visual`）；`tutor_shape.lint_shape` 只记录；`tutor_visual.py` 四种图型（`steps`/`compare`/`segment`/`number_line`）；`vet_candidate` 对图单独处理；新组件 `tutoring.visual-leak-judge@v1`；`text_visual` 投影；App `VisualBlock`。
- 决策：
  - **图的任何问题只丢图**（非法、超预算、`unknown` 带数值、答案标记、判官判泄露、判官超时/异常/不支持图），文字照常；文字泄露仍整轮回退，与改动前一致。这是延续 114/115/119 的原则：与"孩子能不能看到作业答案"无关的缺陷不能把可展示的回答换成固定话术。
  - 图判官是**独立提示词与组件**，与文字判官并行；判官入口用 duck-typing（`getattr(judge, "visual_leaks")`），不改 `LeakJudgePort`，没有该方法的判官一律按"判不准"丢图。
  - 结构不变量放在 schema 层：`unknown=true` 的量不得带数值，label 里也不得有数字（只查数字字符，不查中文数词）；数轴上的未知标记没有位置，客户端在图旁用提示标出。这是挡住"图上直接标出答案"最便宜的一道。
  - `visual` 只在 `shape_by_act` 里解析：不适用的 `act` 直接丢，非法就整张丢并写 `visual_dropped`（该字段 `exclude=True`，且解析前先丢弃模型自报的值）。
  - 不写 journal；App 里图只属于最近一轮，下一次发送就清除。
- 偏差（设计文档原稿的假设与现状不符）：
  - 伴学对话现状没有 SSE（`TEXT_DELTA`/`INTERACTION_READY` 只在协议文档里），是一次请求返回完整 `next_interaction`；所以"流式不携带图"这条在当前传输下天然成立。
  - 答疑轮次的 `next_interaction` 本来就没有 `kind`/`parts`；带图时才合并 `build_interaction` 的信封，无图轮次不动。
  - 视觉段落没做条件拼接，静态提示词 2,462 → 3,806 字符（+55%）。
- 测试：`test_tutor_shape.py`、`test_tutor_visual.py`（含"提示词里的每个 JSON 示例都必须通过契约"）、`test_visual_vetting.py`、`test_tutoring_visual_projection.py`（计数与事实写入不受图影响、安全审核读到图里的文字）、评测 grading/report；`visual_block_test.dart` 与 `app_ui_test.dart`。服务端 481 项、Flutter 全部通过，`flutter analyze` 无新增问题。
- 没做（需要你或真实数据）：真实模型 K=5 对照评测未跑；视觉未在真机上目测；§十 第 0 步现状度量与教研盘点；`geometry`/`layers`/`relation`。
- 坑：
  - `tests/support/fakes.StaticLeakJudge` 没有 `visual_leaks`，带图的作业轮次会因此丢图（这是 fail-closed 的预期）；要保留图的测试用 `StaticVisualLeakJudge`。
  - 工作流在任务进行中且非作业成果时会给 `content` 追加回任务提醒句，断言文字时用 `startswith`。
  - Flutter 测试里发送按钮要在 `enterText` 之后 `pump()` 才可点；聊天面板是滚动的，找图用 `skipOffstage: false`。

## 追加决策：放宽 relation 红线，日志补输入
- 红线只有一条：不直接给答案。`check_authority` 不再因“受保护题 + `act=answer`”整轮回退，改为答案标记 + 泄露裁判（fail-closed）按内容判定；`act=answer` 永远不开启/放弃/推进题目记录。原因：首次真实回合里模型把知识问题标成 `answer + relation=new`，整轮被固定话术替换，而内容本身无害。
- Grafana 现在记录孩子问话（`input.text`，遮蔽邮箱/手机号，上限 2000 字）；本地审计文件新增 `input`、`turn_result` 两类行，与 `output` 用 `trace_id` 连接。`tutor.turn.result` 事件给出 act/relation/结果/失败原因/配图丢弃原因。Loki 权限与留存按儿童数据处理（见 `docs/observability.md`）。
- 坑：测试里要看到真实 trace_id 需要 `OTEL_SDK_DISABLED` 未设置，否则 span 无效、`trace_id` 为空串。

## 追加修复：保护归代码，提交 ≠ 披露
- 漏洞：上一版 `check_authority` 以 `relation in {same,new}` 决定是否检查，模型标 `none` 就绕过标记检查和泄露裁判。现改为 `permit.answer_protected or claims_work`，与 `relation` 无关；`has_open_problem` 参数删除。
- `submitted` 原来直接解锁（permit 只看 `status==open`，且 `_open_problem` 只取 open 行）。现在 `ProblemState.disclosure`（protected/released）与 `status` 分开，`PROTECTED_STATUSES={open,submitted}`，工作流取最近的 open/submitted 行。`released` 目前没有任何代码路径设置（披露策略待产品决定），所以提交后答案一直受保护，对应“只能帮核查、不断言答对”。
- 影响：提交后孩子追问答案会过泄露裁判；`disclosure` 暂未持久化（没有放行路径，无需列）。
- 遗留：v3 契约（`work|non_work` 判别联合、`topic`）仍未做。

## 追加：契约升到 tutor-turn.v3（提示词 v6，组件 tutoring.turn@v6）
- `work`（WorkAssessment）改为 `turn`，`work | non_work` 判别联合：只有 `work` 分支带 relation（只剩 same|new，必填）/student_move/progress/evidence/next_subgoal；`non_work` 带 `topic`（atomic_lookup | spontaneous_curiosity，未知按 atomic_lookup）。
- `act` 是业务类型：`guide` ⇔ work 分支（缺失或非 work 是结构错误，重试一次）；`answer` 配 non_work。**但 `answer` 带 work 分支不拒绝**：把新作业题误标成 answer 的情形，若强制改成 non_work 会放掉泄露检查，所以保留“声称作业 ⇒ 受保护但不推进题目”。
- 好奇心事实只由 `topic=spontaneous_curiosity` 触发，不再从“不是作业”推导；atomic_lookup 不写事实。
- `turn` 缺 `type` 时，仅凭自己的字段（有 relation→work，有 topic→non_work）推断；其他一律不猜。`relation=none` 不再存在。
- 评测数据集无需改（用例不含契约字段）；`tutor_raw` 测试夹具仍接受 relation=none|same|new 并翻译成 turn。
- 遗留：真实模型上 v6 是否稳定产出合法 turn 未验证（需要 K=5 评测）；披露策略（何时 released）待产品决定。

## 追加：核心原则改写（只改文档，代码和提示词尚未跟进）
- 核心原则写进 `domain-tutoring.md` 顶部“核心原则”节与 PRD §1.2 第 7 条：目的是引导孩子思考与练习；是否直答看“有没有逻辑层次/需要孩子亲自推理”，不看“是不是作业”；红线收窄为“推理成果不被代替完成”。
- 判断 work/non_work 靠模型语义（三个问题 + 三类线索），保护仍由 permit 兜底，因为判错代价不对称。
- 已知差距：作业里的纯记忆提问（填空里的单词拼写）仍会被泄露裁判拦；需要 `work` 分支加“回忆/推理”声明 + 裁判标准改为“是否给出推理结果”+ 对抗评测。`97103aaf-02` 的期望待改为 answer 为主、guide 也接受。

## 追加：work 分支加 depth（提示词 v7，组件 tutoring.turn@v7）
- `turn.depth`：`atomic | recall | reasoning`，只在 work 分支，缺失/未知取 `reasoning`（最保守）。名词，不用动词（不叫 ask）。
- 作用只是**指导回应**：atomic/recall 在作业里也直接 `answer`（可补词根、记忆法），不让孩子猜；`reasoning` 走 `guide`。不放宽保护：`answer` 带 work 分支仍过标记检查和泄露裁判，也不推进题目。
- 裁判标准不变（“是否给出本题答案”）。问的东西恰好是空格答案时，模型要改 `guide` 给最小提示；说出来就被裁判拦、整轮回退。接受这个保守。
- 判断是不是作业只看上下文（有无进行中的题、前几轮、尝试/求提示、截图是否题目），不从任务标题猜（标题里看不出推理部分）。
- `97103aaf-02` 期望改为 answer 为主、guide 也接受（`outcome_in=[answer,hint_like]`）。
- 待验证：v7 需要跑 K=5；重点看 atomic/recall 在作业里的 answer 比例，以及有没有把推理题标成 atomic 的偏差（对抗用例尚未建立）。

## 追加：方案 A 落地（泄露裁判 v2）
- 事实：depth-04（听写问空格词）在 v7 评测里 0/5 全回退。原因不是模型违规：模型把它标成 `non_work/atomic_lookup`，permit 又因 open 的题受保护，裁判提示词只有“是否给出最终答案”，所以每次判泄露。
- 方案：裁判升 `tutoring.leak-judge@v2`（提示词 v2，输入契约 v2），输入可带 `depth`；`tutor_loop._fact_depth` 只在回复 ≤200 字且（work 的 atomic/recall，或 non_work 的 atomic_lookup）时才传。裁判规则：单个靠查询/记忆的事实放行；计算结果、推理结论、选项、对错无论标签都算泄露；没有 depth 按原标准。答案标记检查不变。
- `LeakJudgePort.leaks` 新增可选 `depth`；fake 记录 `depths`。
- 评测：新增 depth-05（计算）、depth-06（判断）对抗用例；depth-04 期望改为 answer。针对性回归：depth-00~06 与 guard 共 10 例 50 样本，只有 depth-06 因措辞含糊先出现 clarify，改写后 5/5。完整集的全量复跑尚未做。
- 坑：判官的放行靠模型自述 + 长度上限，是整套保护里最松的口子；调提示词或换模型后必须重跑 depth-adversarial 标签。
