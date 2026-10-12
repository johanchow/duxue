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
