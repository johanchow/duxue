# 到点邀请接到首页

日期：2026-10-06

- 决策：`StartCue` 的打开、评估、呈现和按钮由 `StartCueService.sync` 在读取当前邀请时完成。没有现场时用 `no_observation`，句子用策略兜底，不调用视觉模型和文案模型。
- 接口：`GET /start-cues/current`，`POST /start-cues/{id}/commands`。首页在问候语下渲染 `presented` 卡片。
- 未接：到点前的观察租约和真实场景分类。`away` 只在服务传入该标签时保持不展示。
