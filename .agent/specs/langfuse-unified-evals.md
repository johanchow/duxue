---
slug: langfuse-unified-evals
status: in_progress
created: 2026-11-11
---
# 统一评测数据与评分

用户已确认上一轮7步方案并授权实现，作为计划Gate 1。Langfuse维护Dataset、检查点要求、Evaluator与Score Config；本地只执行项目代码、传输证据和汇总云端结果。

## 验收
- [x] 41份用例幂等导入5个Dataset，来源/标签/固定历史保留；版本可固定，Git仅保留初始化/历史快照。
- [ ] 全部执行类型支持远端输入与原生评分；缺图片、超时、缺分、重复分不得计通过。
- [x] 6个现有核心Evaluator复用，独立离线规则不影响生产；旧评分逻辑不再是默认执行入口。
- [x] 本地执行对应Experiment，记录数据/配置/代码/裁判版本与检查点证据。
- [x] Admin读取新维度/API+EVAL来源，不混用旧answer_quality及门禁分。
- [x] 本地测试通过；8例接通验证后全量41例运行，失败如实保留。

## 计划
1. 验证SDK/API、原生代码及多模态裁判协议。
2. 实现幂等迁移/导出、远端版本固定及运行协议；分离执行与评分。
3. 配置离线规则、评分等待及状态汇总；适配Admin。
4. 测试并运行真实用例，记录结果与限制，供用户验收。

## 验证进度与阻塞
- 8例真实接通运行并用 resume 回收原生评分：6 pass、2 fail，0 error；失败保留，不改业务Prompt或降低标准。
- Admin 37项测试、类型检查、构建通过；真实 Experiment API 聚合已返回两个教学维度、保护、安全、任务状态和排除评分等待的延迟。
- 41例真实回归已结束：34 pass、6 fail、1 error，结果在 `duxue-server/var/evals/langfuse-unified-all-41/`；图片原生裁判拒绝现有DashScope自定义模型的JPEG输入，已向用户询问是否接入兼容视觉连接。不能因Code通过而计整例通过，不回退本地Judge。
- 浏览器工具启动失败（sandboxPolicy缺失），未完成页面视觉验收。无提交、发布或部署。

- 最终Server评测单测212通过；全量报告与5个Experiment链接见本地结果目录 REPORT.md。图片原生评分及页面视觉验收仍未完成，保留spec待处理与验收。

- 2026-11-12 Scores默认可见完成：新任务根、检查点、9条Score实测均为offline-evaluation；离线规则同步兼容新旧环境。新增2个边界回归，220测试通过，云端真实1例pass；验收Experiment e8a44be21a9561d3。历史记录不改写，页面当前若保留SDK环境显式筛选需清除。

- 2026-11-12 用户已要求归档图片用例及turn-visual-leak-00，当前ACTIVE为39例；图片连接兼容性保留为未来含图评测限制，不重写历史结果。用户授权本地commit；提交前再次验证Server评测220测试/静态校验/lint，Admin37测试/类型/构建全部通过；保留本spec记录尚待人工校准及浏览器视觉验收事项。
