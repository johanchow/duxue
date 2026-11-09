---
slug: agent-prompt-fragments
created: 2026-11-08T10:42:46Z
status: review
---

# Agent 具名模板与静态工具结果

## 做什么 / 为什么
将影响模型行为的固定修复/条件指令及SVG规范纳入现有Agent/Tool的版本化配置；不增加模型调用、不迁移摄像VLM。

## 验收标准
- [x] Prompt支持具名fragments、显式变量、未知字段/变量错误拒绝；旧配置继续可加载。
- [x] 静态Tool仅可只读，由注册处理器读取static_result；启动校验输出契约，调用返回独立副本。
- [x] 答疑修复/图片核验/自述提示及Planning窗口规则迁移；条件、输入授权、重试与审核仍归代码；发送正文保持一致。
- [x] 配置摘要覆盖片段和引用Tool，CLI可查看，模型观测/离线评测可追溯。
- [x] 相关与服务端全量测试、配置校验和修改文件静态检查通过，文档/笔记同步。

## 实现计划（Gate 1）
用户已在本轮“好的，继续”确认上一轮最小扩展建议，继续实施，不重复请求计划许可。
- Schema/加载/渲染：definitions.py、prompts.py及静态结果处理器；不支持任意条件表达式。
- 配置及调用：tutoring.turn、planning.intake、widget_guidelines；保留既有数据装配与安全门禁。
- 追溯：组件摘要、CLI展开、遥测与评测metadata。
- 验证：先写契约失败测试，再覆盖一次替换、拒绝未知片段、static_result只读/复制、迁移正文不变；现有重试/配图/规划测试与全量回归。

## 实现清单
- [x] Schema及运行时
- [x] 迁移及版本追溯
- [x] 测试/文档/笔记

## 备注
Gate 2：实现与自动验证完成后等待用户验收，再归档。现有摄像头现场测试和未跟踪图片属于其他工作，不纳入本轮。

## 验证证据
- 初始契约测试4失败/4通过；实现后新契约与迁移正文固定摘要回归通过。
- 相关回归426通过；当前工作区全量830通过、1项既有网关二进制集成跳过（23.46秒）。
- Agent定义校验通过；新增文件完整Ruff及本轮修改Python的F/E9/I检查通过；git diff --check通过。
- 主要版本：tutoring.turn v21、backup v4、planning.intake v6、widget_guidelines v2。主Prompt正文和模型参数保持原样。
- 尚未提交/部署，等待Gate 2用户验收。
