# 167 Tutoring 视频回答的文档与领域边界

日期：2026-10-26。范围：设计修订，未实现代码。

- 决策：Ward 请求单个知识问题的讲解视频，是 Tutoring 的异步回答形式；暂停后围绕视频追加问题，仍走 Tutoring 的当前教学许可与出口检查。无需新增 Exploration & Explainer Domain 或 Bounded Context，也无需给 `companion.intent` 增加 `exploration` 标签。
- 文档归属：`domain-tutoring.md` 是 Tutoring Context 唯一领域主文档；较长的制作、媒体时间轴与渲染细节放在 `docs/technical/tutoring-video-answer.md` 专题补充，避免以 `domain-explainer.md` 命名暗示新 Context。Companion 只维护 Thread/Run 和交互信封。
- 生命周期：拟用 Tutoring 内的 `VideoAnswer` 管理异步制作与已审核产物引用；它不依赖长期保持打开的 `StudySession`。当前 `TutoringSession` 仍依附 StudySession，实施视频追问前须补不依附已结束 StudySession 的受权答疑会话路径。
- 证据：可受控检索新主题；关键断言须定位到实际来源版本与证据片段，来源标签或模型自报置信度不构成证据。请求与成稿均受当前具体题目推理成果保护，任务标题相似不构成拒绝理由。
- 坑：服务端未知时刻完成的渲染任务不能借用 `start_cue` 的本地定时通知实现后台完成提醒；P0 先在原消息中更新状态。
- 播放与修改：现有对象存储是阿里云 OSS，私有 MP4 经受权 Query 返回短期签名地址供 App 播放；追问必须绑定 `artifact_version` 与秒/时间区间，再由服务端映射到已审核 beat。视频修订以脚本/产物不可变版本发布。
- 协议决策：`VideoAnswerScript.v1` 是唯一可编辑的教学与画面语义源，用稳定 scene/beat/对象 ID、概念依赖、证据引用和画面交接支持 Agent 理解与修订；`VideoAnswerTimeline.v1` 是逐句 TTS 与渲染后生成的只读时间索引。首版按 scene 独立渲染、内容哈希缓存和片段拼接；旁白时长变化仍会重算后续绝对时间轴，受影响 scene 以外的片段可复用。接缝或音画校验不过则回退全片重渲，发布失败保持旧版。详见 `docs/technical/tutoring-video-answer.md` §五。
