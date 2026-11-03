# 计划与任务

事实源：[计划 PRD](../../docs/product/prd-schedule.md)、[Planning 领域](../../docs/technical/domain-planning.md)。

## 目标

普通 Task 记事、Plan 按需提供顺序提示；首页不常驻当前/下一项，只有主动开启的限时 Sprint 展示挑战卡。完整规则归属 PRD，不要求孩子维护状态。

## 状态

- 2026-11-03 用户进一步确认 v3.2：替代 v3.1 的默认当前/下一项展示，普通计划仅按需提示，明确授权的 Sprint 才有首页限时卡。代码尚未实现本轮调整。
- 本轮仅修改文档，代码仍含旧版任务池、时长/时间槽门禁、常驻计时等，尚待实现验收。执行中调整、可空时间及无会话完成声明不视为已落地。

## 决策索引

- 展示、可选估时、按需查看全部已知作业及邀请边界见 [PRD §三至四](../../docs/product/prd-schedule.md#三前台展示与入口)。
- 主动挑战的开启/到时与任务完成分离见 [PRD §4.4](../../docs/product/prd-schedule.md#44-专注挑战sprint)，执行归 [Study Sprint](../../docs/technical/domain-study.md#24-sprint主动专注挑战目标扩展)。
- 安排/开始/完成分离、目标绑定、版本与幂等，以及迁移边界见 [领域设计](../../docs/technical/domain-planning.md)。
- 净书写、会话计时、完成耗时不得混用；证据边界见 [Behavior](../../docs/technical/domain-behavior.md) 与 [Study](../../docs/technical/domain-study.md)。

## 现有实现注意（迁移前，不能作为目标产品规则）

- 计划提示词是 f-string，示例 JSON 花括号写成 `{{` `}}`。
- DashScope HTTP 客户端必须 `trust_env=False`，失效代理会让整理一直不可用。
- 确认关掉 Run，下一句是新 Run。指代读同一 Thread 最近 8 句、合计 2400 字、不含本轮。
- 现有代码仍可能有时长必填门禁；目标改为有标题即可登记，迁移前不能宣称已支持。`operations` 为空时不能说已记入任务池。
- 现有首页有19:00/30分钟展示回退，目标需移除，不能写回或视为真实时间。
- Dart 解析带 `+08:00` 的时间可能变成 UTC，展示前转上海固定偏移。
- 过了本地日的 `scheduled` 必须回任务池，否则再安排到今天会找不到可改任务。旧那天的日程保留。
- 同一开始时间写到多个任务上要清空并澄清。前一项结束等于后一项开始不算重叠。
- 接口字段仍叫 `assignment_id`，领域身份是 `task_id`。
- 左滑删除不能删已排期、有学习记录或 `source=guardian` 的任务。已有学习记录返回 409。
- 拒绝日志只记稳定错误码和值的形态，不记原话和标题。
