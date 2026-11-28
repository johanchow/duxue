---
slug: conversation-artifact-journeys
created: 2026-11-28T07:10:41Z
status: awaiting_acceptance
---

# 双端多对话与可保存产物

目标与契约见[教育 Agent PRD](../../docs/product/prd-edu-agent.md)、[Conversation](../../docs/technical/domain-conversation.md)和[ArtifactWorkspace](../../docs/technical/domain-artifact-workspace.md)。

## 验收标准

- [x] Guardian 无学生也可直接进入工作台，在 A 发起课件制作，切到 B 备课。A 的迟到结果写回 A。重新打开 App 后可以找到两个对话。
- [x] 已保存课件重开、修订、撤销和重做仍可用。删除来源对话后仍能从资源库打开同一份课件；清空后迟到回复不能恢复旧消息。
- [x] Ward 在 A 做题、在 B 共创图文绘本。能语音局部修改、撤销、重做和保存，冷启动后能从「我的作品」重开。新线程中重新索取作业答案仍受保护。
- [x] 服务端按账号和角色授权；同一账号的两个线程分别取上下文与资源引用；成人体验学生视角继续与真实 Ward 数据隔离。
- [x] 请求重试只产生一次写入；断线后能恢复最终结果；迁移核对联调 PostgreSQL；服务端、Flutter 和 Android 入口均有验收记录。

## 实现计划

1. 以真实入口补失败测试。检查 ConversationThread、CompanionMessage 的字段、索引和外键，增加支持 guardian/ward 的线程归属、每线程代际与消息查询。完成默认续接、新建、列表、切换、清空和删除的服务端契约。旧测试聊天无需搬迁，已有保存课件保持原 ID。
2. 接入 guardian_experience、guardian_courseware 和 GuardianQuestionPage。会话历史和产物引用由服务端保存，模型调用前读取本线程上下文；异步结果按原 thread 和代际落盘。App 切换时隔离草稿、图片与进行中状态，Flutter 验重启和删除源对话后的资源库访问。
3. Ward 首页复用线程接口。用 creative_work 打通绘本生成、语音局部修订、版本指针和主动保存。复用既有产物版本与保存机制，校验角色和当轮教学策略。扩展 Admin 测试配置时记录实例回读。
4. 按以上两个旅程回归真实入口，核对 Android 页面、API 结果、数据库状态及模型 trace。后续成人批改诊断单和变式卷另行验收。

## 当前进度

- [x] 核实现状：Guardian 会话按视角存于页面内存，服务端通过 state_token 续聊；课件 ID 写入页面消息。Ward 已能创建线程记录，清理与读取仍使用 Ward 级历史代际。
- [x] 开工基线：Guardian 问答、课件 API 和保存课件 PostgreSQL 用例 49 passed；Flutter 问答与课件页面 20 passed。
- [x] Gate 1 具体计划确认
- [x] 线程契约与持久化
- [x] Guardian 课件闭环（服务端真实模型 + PostgreSQL + Flutter）
- [x] Ward 作品闭环（含 Android 真机）
- [ ] 真机验收与 Gate 2

## 本机验收记录（2026-11-28）

- 测试 Admin 草稿 revision 9，已从在线服务回读；工作草稿包含绘本生成与独立代写 Gate。已有 Langfuse 用例 `pedagogy-remainder-next-step/check-1` 在此配置通过。
- 实际业务库 `duxue-test` 已到 `20261128_44`，核对了线程独占归属约束、作品版本和只在保存后写出的足迹事件。
- 无学生绑定的成人账号由真实 API 在 A 生成课件、切到空白 B、回到 A 找到相同 ID，保存后删除 A，重开课件修订到 v2，撤销到 v1，再重做到 v2。Flutter 另测切换线程时迟到回复的隔离。
- Android 设备 `cf2b78d6` 用 Ward 语音生成《小青蛙的月亮船》两页绘本，将第一页改成红色小船；实机逐次核对撤销、重做的原文与图，结束 App 进程后从「我的作品」重开得到已保存的新版本。
- Guardian 独立 Android 测试包新安装被系统取消，成人验收目前覆盖真实 HTTP 入口与 Flutter widget。Gate 2 由使用者验收后归档。
- 最终回归：服务端全量 1617 passed、4 skipped；绘本命令最终针对性复跑 6 passed；Flutter 全量 204 passed，静态分析通过，更新后的 debug APK 已装入已绑定的真机。真实作业代写请求分别在两个新线程中路由至 `current_turn_teaching_policy` 并收到启发式答复。
