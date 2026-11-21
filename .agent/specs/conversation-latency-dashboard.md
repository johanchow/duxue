---
slug: conversation-latency-dashboard
created: 2026-11-21T01:00:24Z
status: draft
---

# 对话端到端耗时看板

## 验收标准

- [ ] Guardian 和 Ward 每次实际发送问题时在 App 启动单调时钟。完整回复进入当前对话的可展示状态时停止。语音转写需要确认发送时从确认发送起算。流式回复持续计时至终态。
- [ ] 每次成功、失败、超时或取消有唯一轮次标识。完成事件独立于链路采样，上报重试保持同一标识并去重。明细展示实际完成时间、入口、结果、耗时及可用链路，支持按时间范围、环境、入口筛选。
- [ ] 平均、P95、P99 和成功样本数使用同一窗口内的成功轮次，失败、超时和取消单列计数。无数据时显示无样本。验收包含超过 80 秒的轮次，并说明分位数算法或近似误差。
- [ ] 统计覆盖已启用遥测且完成上报的 App 版本，区分测试和生产。使用匿名轮次标识，明细字段限于排障元数据。

## 实现计划

1. 在 duxue-app 的 Guardian、Ward 发送与完整回复交付入口接入统一计时，复用 core/telemetry.dart 和现有认证中继。处理清空历史、迟到响应及断网补报。核对目标构建的遥测开关。
2. 在 duxue-server 的 client-events 中继和 observability 层校验并上报轮次事件。以同一去重样本集生成逐轮和聚合查询，使用覆盖长尾的耗时值。轮次及 trace 标识只作明细字段。
3. 在 ops/observability/grafana/dashboards 新增独立看板定义，更新 docs/observability.md。在已连接 Grafana 发布并回读验证各面板。
4. Flutter 和服务端测试覆盖两入口、完整回复、错误、超时、取消、重试及采样关闭；以已知耗时样本核对平均和分位。使用真实测试端请求核对客户端计时、明细及统计，提交验收。

## 完成度

- [x] App 计时与上报
- [x] 中继、去重与查询
- [x] 看板 JSON、全部面板查询及说明
- [ ] 保存到 Grafana Cloud 并回读面板（当前连接缺少 dashboards:create / dashboards:write）
- [ ] 自动化测试及线上看板联调验收


## 联调证据

- Android 模拟器 Guardian 发出真实问题，完整回答出现后 Loki 回读 5060 ms，关联的服务端 trace 为 `f24d824cbc7876f3f4c4e6c9fc0a61b4`。
- Android 模拟器通过 Ward 的实际转写提交入口发问，等待 90031 ms 后超时，Loki 回读 timeout，轮次 58d5ea7bb8ff203cbacfbad615fb6f5a。
- 隔离 `latency-qa` 样本 1000、81000 ms 成功，1500 ms 超时。重复投递 81000 ms 后各面板查询仍返回两个成功轮次和一次超时。看板 reducer 采用原始样本排序，平均 41000 ms，P95/P99 均 81000 ms。
- 云端创建返回 HTTP 403，权限回读仅有 dashboards:read 和 folders:read；待有写权限后验收线上渲染。测试事件可从 [Explore](https://johanww.grafana.net/goto/s85jsv) 查询。
- Flutter 全量 177 项通过，服务端遥测 28 项通过。服务端全量 1416 passed、1 skipped、9 个集成测试在迁移降级 fixture 失败；现有 ORM 创建的外键名称与 20261120_38 降级期望的 fk_ward_owner_guardian 不一致。
