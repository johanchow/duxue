---
slug: app-mockup-alignment
created: 2026-08-22T00:00:00Z
status: draft
---

# app-mockup-alignment spec

## 做什么 / 为什么

将当前以 Material ListTile 为主的 Flutter MVP 界面，升级为与 `docs/mockups` 一致的移动端信息层级和交互：Guardian 以「孩子 / 决策 / 我的」为主、进入孩子详情后查看今日/报告/设置；Ward 以今日行动、AI 伙伴与成长为主。保留现有 API 和权限边界，优先让已具备后端能力的流程可用。

## 验收标准

- [x] 建立可复用的 App 视觉基础（颜色、圆角卡片、间距、状态标签、底部导航），整体视觉与 mockup 的蓝色、浅灰背景、圆角卡片层级一致。
- [x] Guardian 首页改为 3 Tab：孩子列表、决策、我的；孩子页支持新增档案和多选 Ward 的传递入口，传递 sheet 呈现文字/语音/截图入口，并明确不会直接修改 Ward 已确认计划。
- [x] Guardian Ward 详情改为今日/报告/设置三 Tab：今日只显示设备知情状态、计划进度和任务池；报告显示「今日等待生成」及可看的过往/趋势入口；设置收纳档案、设备和高级分析配置。
- [x] 现有 Guardian 能力可从新界面抵达：新建 Ward、设备邀请码、任务提交、日报、周趋势、分析配置、退出登录；请求失败有可理解反馈。
- [x] Ward 绑定后进入与 mockup 一致的 3 Tab 学习空间：首页（计划/任务及观察控制）、AI 伙伴（现有问答接口）、成长（今日反馈等待生成 + 历史趋势）。
- [x] Ward 能建立/确认计划、开始/结束学习会话、提交自评并看到当天双轨事实摘要；观察控制仅显示记录状态、关联任务、时长和暂停/结束，不显示实时专注判定。
- [x] 对新增/改动的 UI 状态和模型转换补充 widget/model 测试；`flutter analyze` 与 `flutter test` 通过。

## 实现计划（Gate 1：填完等人确认，不许自转）

- 影响文件：
  - `duxue-app/lib/main.dart`：补充全局 Theme 与 Guardian/Ward 角色入口路由，保持既有 Guardian API 登录与 Ward 绑定流程兼容。
  - `duxue-app/lib/features/ward_pages.dart`：重构 Guardian 首页与 Ward 详情为 mockup 对齐的导航和卡片；将现有设备邀请码、报告、趋势、分析配置导航接入详情页。
  - `duxue-app/lib/features/day_story_pages.dart`：重构 Ward 今日、伴学和成长工作台；复用既有计划、会话、问答、自评、洞察 API，增加观察状态控制与“今日等待生成”状态。
  - `duxue-app/lib/features/login_page.dart`：将 Guardian/ Ward 的入口改为符合角色选择语义的登录首屏。
  - `duxue-app/lib/features/report_page.dart`、`profile_pages.dart`：套用统一视觉组件，并将报告呈现由数字优先调整为事实/节奏/建议优先。
  - `duxue-app/lib/shared/`（新增）和相应测试：沉淀通用卡片、状态标签、空状态、底部导航等组件，新增关键 widget 测试。
  - `.agent/notes/004-app-mockup-alignment.md`：记录 UI 与产品边界决策、API 适配限制和验证结果。
- 实施顺序：先建立主题与共享组件；再完成 Guardian 主导航和详情；随后重构 Ward 工作台；最后套用报告/设置页面、添加测试并用模拟/已配置 API 做回归。
- 测试计划：运行 `flutter analyze`、`flutter test`；新增 widget 测试验证 Guardian 的三 Tab/传递说明、Ward 成长的今日等待与历史信息、观察控制不显示实时行为结论；在可用模拟器或本地服务中人工走通 Guardian 创建档案→传递任务→Ward 计划/自评→Guardian 报告入口。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）

- [x] 建立主题和共享 UI 组件
- [x] 重构 Guardian 主导航与多模态传递入口
- [x] 重构 Guardian Ward 详情、报告与设置入口
- [x] 重构 Ward 今日、AI 伙伴、成长空间
- [x] 补充测试与运行 Flutter 验证
- [x] 记录决策、审查 diff 并等待验收

## 备注

- 本期不新增服务端接口、不实现真实语音识别或图片上传；界面会提供对应入口与清晰的待接入状态，文字任务提交沿用现有 API。
- 当前 API 对 Guardian/ Ward 有不同认证方式；重构不得把客户端隐藏按钮当作权限控制，继续由服务端接口鉴权。
