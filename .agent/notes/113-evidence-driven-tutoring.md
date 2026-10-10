# 113 证据驱动的过程题答疑

日期：2026-10-10

事实源：`docs/technical/domain-tutoring.md` v3.1 §1、§2.3、§4.1–4.2、§8。

- 原子知识（字怎么写、词义、翻译、发音、看图事实）可直接回答；是否处于作业、听写或填空会话中不自动收紧。受保护的是本轮请求是否要求交付最终答案、待填内容、选择项、完整解法或代写成品。
- 过程题不再使用尝试次数或连续卡住次数放行完整答案。每轮只给一个最小教学目标；只有 Ward 对当前目标产出可关联的思考、判断、式子、草稿或解释，才能进入下一个目标。卡住时换表征、拆目标、给同构例题或建议待问老师。
- `submitted` 表示 Ward 已提出完整思路/答案；在未接入题型校验器前，模型不得断言答案正确或孩子已掌握。未来可按高频结构化题型接入可选校验器，不建设通用数学程序。
- 未成年人安全不能只依赖主答疑模型自述。输入和最终 Ward 文本都经过 `SafetyScreeningPort`；适配器可复用统一 moderation、专用安全分类模型，或仅用于高风险边界的独立 Judge。
- 本轮不建设离线评测、A/B 实验或质量大盘；保留已有脱敏 Trace、fallback、审核拒绝和版本字段，供后续评测使用。
- 拆分后，`ProblemRecord` 只保留 `ProblemStatus`（`open` / `submitted` / `abandoned`），不重复持有答案状态、验证状态或已完成小目标；答疑事实、题目状态与 Outbox 都归 Tutoring。回任务提醒由 Application 基于 Study Query 投影，不进入 `TutorPermit`。

实现（2026-10-10）：`TutorPermitPolicy` 已迁至 `app/contexts/tutoring/domain/`；`tutoring_problems` 由迁移 `20261010_25` 删除 `solution_state`、`no_progress_streak`、`answer_requested`，新增 `active_subgoal`、`evidence_summary`，并将旧 `solved` 映射为 `submitted`。`SafetyScreeningPort` 注入答疑工作流，默认本地高风险预检覆盖输入和输出；后续可替换为统一 moderation 或独立分类器。
