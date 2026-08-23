# Guardian 对话式任务传递

- Guardian 的自由文字、语音转写和图片经 `qwen3-vl-flash` 整理为候选任务；候选任务与聊天历史只存在 Flutter 当前底部弹窗状态，关闭即丢弃，只有确认后的 `assignments` 是持久事实。
- LLM 的 Ward 白名单由服务端实时从 `guardian_ward_relations` 查询；多 Ward 时，输入没有明确归属必须返回追问，禁止模型默认复制、依据历史或年级猜测。确认 API 再次逐项校验关系并在单个事务中创建任务。
- 对话接口采用简单 JSON（assistant 文本、任务清单、澄清状态、问题、可确认状态）来驱动聊天气泡和只读任务组件；当前不引入完整 AG-UI runtime，后续需要工具调用流时可在该响应之上演进。
- Guardian 图片写入 `guardian/<guardian-id>/task-intake/` 临时路径，解析/确认都验证该前缀和对象存在；确认或退出时尝试删除，生产 OSS 仍应配置同前缀生命周期规则兜底清理。
