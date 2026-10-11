# 120 答疑契约 v2：按 act 嵌套，元数据不一致不再整轮回退

日期：2026-10-11

事实源：`docs/technical/domain-tutoring.md` v3.2 §4.1–4.2；spec 见 `.agent/specs/tutor-turn-contract-v2.md`。

- 现象：114、115、119 反复出现同一类故障——与孩子安全无关的字段不一致（`confirm` 无 `solved`、`lesson`/`candidates` 与 act 不匹配、错位的 `question_kind`）把本可展示的回答换成固定兜底话术。每次都靠给校验补例外。
- 根因：`tutor-turn.v1` 是 14 个字段的扁平对象，同一件事有多个自述信号（作业关系：`question_kind`/`is_assignment_content`/`same_problem`；泄露：`reveals_solution`/`act=answer`；孩子行为：`student_turn_kind`/`progress`），`act` 与 `question_kind` 是两个互相渗透的轴，`confirm` 一词两义（与领域的 `submitted` 语义也冲突）。跨字段 `x_without_y` 校验把元数据矛盾升级成整轮失败。
- 决策（项目未上线，一次做完）：
  - 顶层只有 `act` + `content`；`work`（`relation`/`student_move`/`progress`/`evidence`/`next_subgoal`）、`clarify`、`pronounce` 是只属于对应 act 的子对象，不适用就丢弃。
  - `act`：`answer`/`guide`/`chat`/`clarify`/`redirect`/`pronounce`/`safety`，互斥。去掉 `confirm`、`probe/hint/example`（合并成 `guide`）。加 `chat` 是为了保住「知识问答记好奇心、闲聊不记」的区分，否则去掉 `question_kind` 后无处承载。
  - `progress=solved` 改为 `submitted`；提示词写明模型不能断言对错。接收孩子提交的一轮不计为提示（`hints_given` 不加、不发 `tutoring.hint_given`）。
  - 出口检查只拒绝会让孩子看到不该看的内容的情形（答案保护、答案标记、泄露判官、发音卡不可用）；元数据不一致只是丢弃或不推进。`act=safety` 只能收紧，独立安全筛查仍是最终裁决。
  - 唯一保留的「缺失即失败」：`answer`/`guide` 必须有 `work.relation`（缺失不猜，走一次结构重试）。缺它就无法判断是否受保护，v1 里同样由必填的 `question_kind` 承担。其它 act 缺 `work` 按 `none`。
- 实现：`tutor_turn.py`（候选、`check_authority`）、`tutor_loop.py`、`tutor_permit.py`（`HINT_ACTS={guide}`、`student_move`、`submitted`）、`tutoring_workflow.py`（`_apply_problem` 以 hints_given 是否增加决定提示事件；curiosity 改为非作业的 `answer`/`guide`）、`evals/outcome.py`/`schema.py`（outcome `confirm` → `chat`）、提示词 `tutoring.turn.system.v3`、组件 `tutoring.turn@v3`。`duxue-app` 不读取 `next_interaction.act`，无前端改动。
- 测试：新增/改写 `test_tutor_turn_exit.py`（子对象丢弃、relation 必填、未知元数据按未报告、保护规则）、工作流用例（submitted 不算提示、无证据 progress 不回退、chat 不回退）、`test_tutor_permit.py`。服务端全量 pytest 全绿。
- 离线评测（qwen3.7-plus-2026-05-26，K=5，16 个 proposed 用例，契约和提示词一起改）：采样通过 70/80 → 72/80；fallback 2/100，原因只剩 `reveals_protected_work_product` 1、`segment_not_in_source` 1；`guard` 5/5、`answer-protection` 5/5、`confirmation` 1/1。局限：全是 proposed；契约与提示词同时改，无法分开归因；样本小。`turn-97103aaf-03`（看图读最后一排）由 4/5 → 0/5、`-02` 由 0/5 → 4/5，都是图片理解类、与契约无关的采样波动，未归因；`-01`（日记里要成语）有 1 次被判成作业而拒绝 answer，是 `relation` 的真实模糊点。结果在 `var/evals/after-contract-v2.json`（不入库）。
- 坑：
  - `tutor_raw()` 夹具改成 v2 形状（`relation=None` 表示不带 `work`）；旧测试里的 `question_kind` 等参数要整体换成 `relation`/`student_move`。
  - 评测数据集 `expect` 只用到 `pronounce`/`answer`/`fallback`，无需改数据。

## 补：作业进行中问英语单词读音（2026-10-11 晚，线上对话）

- 现象：造句任务进行中，孩子问「这几个都分别怎么读」得到「这几个词都是中文成语，先回去造句」（`redirect`）；再说「我是说那几个英语单词都怎么发音」仍没有读音（`clarify`，选项里是 `{ref,text}` 对象）。
- 对照（同一模型，K=8，两个由线上对话还原的 proposed 用例 `turn-incident-00/01`）：改前（v1）两句都 8/8 `clarify`；契约 v2+提示词 v3 后第一句 6/8 `pronounce`，第二句 8/8 `redirect`。所以问题不是 v2 引入的，但 v3 里对 `redirect` 的定义（「把离题的话题带回任务」）让失败从「再问一次」变成了「拒绝并带回任务」。
- 根因：(1) 开放作业题和 `answer_protected` 把模型锚在任务上，把知识/发音问题当成离题；(2) 发音卡一次只有一个 `source_text`，「几个词」没有出路；(3) 「这几个」确实有歧义（上一条里中英文并存）。
- 我引入的 bug：`ClarifyPayload` 把 `{ref,text}` 对象 `str()` 成 dict 的 repr 给孩子看。已改为只取 `text`，其它不可用项丢弃，有回归测试。
- 提示词（`tutoring.turn.system.v4`，组件 `@v4`）只改了一处：`redirect` 的定义改为「孩子要做的事和学习无关时才带回任务；知识和发音问题不是离题，哪怕在做作业也直接回答，回任务提醒由系统补」。字数没有增加。
- 试过并撤回：在 `pronounce` 里加「一次只读一个词，要读好几个时用 clarify 请他选一个」。图片用例 `turn-97103aaf-04`（「这个怎么读」，所指是上一句刚说的英文）从 5/5 `pronounce` 掉到 0/5 `clarify`，模型变得处处追问。教训：给模型加「要不要追问」的规则会整体改变它的追问倾向，副作用大于收益。
- 明确不做：指代规则（「这几个」按孩子刚说的语言选对象）。模型本来就看得到对话，规则会越加越多、无法收敛。
- 仅 redirect 变更后的结果（K=5，pronounce 标签 9 条）：`-04` 5/5；`incident-01` 4/5 `pronounce`（原 0/8）；`incident-00` 2/5，另 3/5 是 `reveals_protected_work_product` 回退——模型对「这几个词怎么读」用 `act=answer` 且把 `work.relation` 标成 `same`，被出口检查拒绝。这是仍未解决的一类：作业进行中，对知识类问题错标 `relation=same`。样本小、均为 proposed，不构成通过依据。
- 多词发音：保持现状（一次只读一个）。提示词层面的约束有副作用，已撤回；若要做，应在产品层处理，而不是加规则。
