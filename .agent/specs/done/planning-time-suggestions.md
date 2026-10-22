---
slug: planning-time-suggestions
created: 2026-10-21T15:53:19Z
status: done
---

# planning-time-suggestions spec

## 做什么 / 为什么
给新任务或当前计划中的任务提供两种独立建议：预计时长根据该 Ward 近 15 天已完成的同名任务实际用时计算；计划开始/结束时间根据确定性的适宜时段规则提醒过早或过晚，不使用历史行为。建议只读、不自动改 Task 或草稿；Ward 明确采纳后，才通过现有 Planning 用例写入。

## 验收标准
- [x] 时长建议只读取当前 Ward 的已完成、绑定 Task 的 `StudySession`。按 Task 标题的现有规范化等价规则匹配，排除当前 Task、无效/零时长、未完成、无任务、其他 Ward 和超出近 15 个本地日的样本；同一历史 Task 最多贡献一次。客户端上报的 `active_seconds` 是计时输入，不称为客观专注时长。
- [x] 至少 3 个可比历史 Task 才给建议。建议采用实际用时中位数，舍入至 5 分钟，限定在 1–480 分钟；返回样本数、历史实际用时的范围/中位数和依据标签“同名任务”，无样本或样本不足时不暗示个性化结论。
- [x] 新任务缺时长时，若有足够历史，澄清卡展示建议但保持候选未登记；Ward 可明确采纳建议或填写自己的时长，采纳沿现有 Slot/Operation 路径登记一次 Task。没有足够历史仍按现有缺时长澄清流程。
- [x] 已有 Task 或计划草稿有 Ward 预计时长时，仅当与建议相差至少 10 分钟且至少 25% 才展示校准建议；Ward 可采纳或忽略。展示、忽略都不修改 Task、时间槽和确认版本；采纳才走已有 UpdateTask / 修订及冲突重验，不能静默改变已确认计划。
- [x] 同一草稿中已拒绝的相同建议不重复劝说；Task 版本、样本或草稿版本变化时重新读取并使旧采纳动作失效。Guardian 对这些动作只有只读权限。
- [x] 计划时间建议只基于 `plan_date` 和草稿时间槽，不读取历史会话。所有学段统一采用 `Asia/Shanghai` 07:00–22:00 的默认建议时段；这是产品默认值，不称为医学或教育标准。开始早于下界或推导结束晚于上界时显示具体原因和可行的新开始/结束时间；没有不冲突的移动方案时只提示，不虚构可行时间。
- [x] 过早/过晚是软建议，不影响 `confirm_enabled`，Ward 可忽略。Ward 已明确给定的时间绝不自动平移；采纳时间建议时保留原时长，重算结束时间并执行现有冲突、当日日期及版本校验。`end_at` 始终由 `start_at + planned_minutes` 推导，不独立写入。
- [x] 相关服务端单元/应用/API 测试与 App 交互测试覆盖建议有无、来源隔离、异常样本、采纳/忽略、幂等、失效和时间冲突；全量测试与本次改动文件静态检查通过。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 决策：时长建议第一期仅做相同规范化标题的历史任务，不引入模型推断“同类”、长期画像或新的持久化统计表；历史窗口为 15 个本地日。时间建议统一采用 07:00–22:00 的静态时段，绝不从历史开始/结束时间推断作息。两种建议都是只读 Query，绝不作为 `PlanIntake` 的默认值。采纳是 Ward 的显式写命令。
- 影响文件：
  - `duxue-server/app/application/queries/`：新增 Ward 授权的 DurationSuggestion Query，从 `Task` 和已完成 `StudySession` 计算 15 日样本、中位数和展示依据；给新候选标题与已有 Task 共用。
  - `duxue-server/app/contexts/planning/domain/`：新增纯确定性的 PlanTimeSuggestionPolicy，按上海本地日与草稿时槽计算过早/过晚提醒及可行的候选时间；统一建议时段集中配置。
  - `duxue-server/app/application/workflows/planning_adapter.py`、`planning_domain_service.py`、`planning_operations.py` 及必要的 Companion 命令协议：把时长建议放进现有缺时长澄清和草稿审阅，把时间建议放进草稿审阅；采纳经原有受控操作/版本门禁，不允许建议自动写入。
  - `duxue-app/lib/features/day_story_pages.dart` 及 API client：分别显示历史时长依据、时间建议及其原因，支持采纳/忽略；维持手动输入时长和时间。
  - `docs/technical/domain-planning.md`：仅更新计划领域建议契约，并链接本 spec；`.agent/notes/` 记录数据质量、边界和实现坑。
- 实现步骤：
  1. 先写两个建议计算的失败测试：时长侧覆盖 Ward 隔离、同名匹配、完成状态、15 日本地日窗口、异常计时、样本阈值和舍入；时间侧覆盖统一 07:00–22:00 时段、过早/过晚、跨日、冲突和无可行移动方案。
  2. 实现只读时长 Query 与纯确定性时间建议策略；用已有 Task/StudySession/Ward 数据，避免新迁移。
  3. 把时长建议接入新候选缺时长和已有 Task 草稿审阅，把时间建议接入草稿审阅；实现 Ward 采纳动作的版本绑定、幂等与旧动作拒绝，复用当前写用例和冲突校验。
  4. 接入 App 显示与交互，补服务端和 Flutter 测试；全量测试、改动文件 lint、diff review 后更新笔记。
- 测试计划：后端 Query/Policy 单元测试 + Planning 应用/协议测试 + Flutter widget/API 测试。特别验证建议计算不引发写入、忽略不会改变草稿版本、采纳已确认任务需修订、采纳后旧时间槽重新计算；软时间提醒不阻止 Ward 确认。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 阅读产品/技术设计、Study 计时来源并建立 spec
- [x] 15 日时长 Query、时间建议策略与数据质量测试
- [x] Planning 建议投影、采纳动作和服务端测试
- [x] App 展示与交互测试
- [x] 全量验证、diff review 与笔记

## 备注
