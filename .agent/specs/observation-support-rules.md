---
slug: observation-support-rules
status: implementing
---
# 摄像头提醒规则与免打扰
方案与验收场景见[技术设计](../../docs/technical/observation-reminder-policy.md)。用户已确认开始实现。业务联调固定使用 duxue-server/.env 的 PostgreSQL duxue-test。
- [x] Admin 草稿和规则运行契约
- [x] 证据连续性与免打扰门禁
- [x] Ward 对话及前台呈现
- [x] PostgreSQL 迁移与回归
- [ ] 实际样本与用户验收

## 系统语音投递

- [x] Ward 前台自动播报、免打扰复核、播放回执、历史邀请过滤和 Agent 朗读独立设置。
- [ ] 后台与进程关闭时推送投递及真机听感验收。
