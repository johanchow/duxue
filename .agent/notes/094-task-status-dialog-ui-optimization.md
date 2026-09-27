# 任务状态流转弹窗 UI 交互优化

日期：2026-09-28

- 现象：按 `domain-planning.md` 和 `domain-study.md` 设计，任务在未排期/计划中、进行中、暂停、完成之间流转时，弹窗采用系统默认 `AlertDialog`，缺少任务上下文（标题、预估时长、计时卡片），操作层次混淆（暂停与完成同级堆叠），暂停状态下无法直接标记完成，且任务完成后缺少正向反馈。
- 决策：
  1. 采用结构化卡片与状态语义色彩（青绿主色、琥珀橙暂停色、深青完成色），为“开始学习”、“进行中操作”、“暂停操作”、“确认完成”设计专属弹窗组件。
  2. 弹窗内清晰展示任务名称、预估/累计时长指示板，保持原业务提示与无缝动画体验。
  3. 进行中操作清晰分离“暂停”（保留时长休息）与“完成任务”（结算记录成果）。
  4. 暂停弹窗支持双向操作：既可“确认继续”恢复专注，也可在已学完时直接点击“完成任务”进入结算，避免多余往复操作。
  5. 任务标记完成成功后，弹出轻量正向成就反馈。
- 实现：
  1. 新增 `duxue-app/lib/features/task_status_dialogs.dart`，封装 `StartTaskDialog`、`ActiveTaskDialog`、`PausedTaskDialog`、`FinishTaskConfirmDialog`。
  2. 重构 `day_story_pages.dart` 中的 `_taskTapped`、`_showActiveActions`、`_showPausedActions`、`_showStartTaskDialog` 与 `_finishSession`。
  3. 在 `test/app_ui_test.dart` 中追加针对进行中与暂停状态直接完成、时长卡片展示的完整 widget 测试并全绿通过。
