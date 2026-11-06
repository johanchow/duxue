---
slug: app-download-page
created: 2026-11-06T13:57:30Z
status: awaiting-acceptance
---

# App 下载页与 OSS 发布

## 做什么 / 为什么
提供固定二维码入口的读学下载页，复用既有签名 APK 工作流，将下载页与版本化 APK 发布到用户指定的 `duxue-download-page` OSS Bucket。

## 验收标准
- [x] 手机与桌面可访问静态下载页；Android 普通浏览器自动尝试下载且保留手动入口；微信展示外部浏览器引导。
- [x] 首版无 iOS 上架链接，明确显示暂未开放，不提供虚假链接；不承诺浏览器会自动接管至安卓商店。
- [x] 复用现有正式签名和版本规则，测试通过后上传版本化 APK，最后更新最新版本元数据；失败时保留既有可用版本。
- [x] 下载页使用同源版本元数据，无需服务端新增接口；二维码长期指向同一页面。
- [x] 发布仅操作下载 Bucket，保留既有 Actions Artifact；静态页面与 APK 分别设置适当缓存和 Content-Type。
- [x] 自动化覆盖设备分流、微信拦截、无发行包/元数据失败、未配置 iOS，以及发布顺序和失败不切换最新版本；浏览器检查移动端布局。
- [x] 域名、HTTPS、公开读及实际 APK 下载完成首次上线验证。
- [ ] 用户 Gate 2 验收并合入 main；确认首次 Actions 自动发布成功及页面构建号更新。

## 实现计划（Gate 1：填完等人确认，不许自转）
- 页面独立放在 `download-page/`，避免被既有 `sites/**` 技术演示 GitHub Pages 工作流意外发布。
- 修改 `.github/workflows/app-release.yml`，沿用 Guardian 签名流程，增加 OSS 发布步骤；增加页面发布工作流及必要脚本。使用 Python OSS SDK（已有服务端技术栈）和已配置的 `production` OSS Secrets，只写入指定下载 Bucket。
- `scripts/tests/` 增加发布流程回归；页面分流使用适合仓库环境的测试工具，遵循实际运行时版本约定；真实下载检查不自动安装 App。
- 更新 `docs/deployment.md` 作为部署事实源，`.agent/notes/app.md` 仅沉淀决策并链接。
- Gate 1：用户已明确确认开发下载页，并要求线上 PR 通过合并到 main 后自动更新 APK。沿用现有签名 workflow，每次 main 推送均触发测试、签名构建和 OSS 发布；失败不切换最新版本。实现后测试与浏览器验证，Gate 2 待用户验收。

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [x] 调查既有签名构建与版本规则，确认 Bucket 名称。
- [x] 确认 OSS 地域、域名/HTTPS、授权方式及 iOS/安卓商店链接现状；用户确认 Gate 1。
- [x] 云端基础设施配置完成：DNS、公共读、静态首页、HTTPS、RAM 最小权限及 GitHub Secrets；HTTPS 证书校验通过。此项不代表页面或 APK 已部署。
- [x] 实现静态页面与分流测试。
- [x] 实现版本化上传、最后更新元数据及发布回归测试。
- [x] 补充部署文档与领域笔记，审查 diff。
- [x] 执行首次发布并验证页面/安装包，进入 Gate 2。

## 验证记录（2026-11-06）

- Node 页面分流与交互测试 9 项通过；Python 脚本/工作流回归 13 项通过；Flutter 原有版本规则测试 1 项通过。JS 语法、Python 编译、工作流 YAML 读取与 `git diff --check` 通过。
- Chrome DevTools 复核390/320宽手机与1280宽桌面布局；微信UA显示引导、关闭后焦点回下载入口；iOS UA明确暂未开放且不自动下载；无横向溢出。Android自动跳转/手动防重复由自动化覆盖，真实小米手机系统安装尚未现场验收。
- 首次APK来自成功的 main 发布 [run 41842043359](https://github.com/johanchow/duxue/actions/runs/41842043359)，并非本地 debug 包。aapt核对应用ID与版本，apksigner验证正式签名；公开HTTPS完整下载63977206字节，SHA-256与原始产物一致。
- 页面GET /、元数据GET/HEAD、APK HEAD均200，HTML/JSON不缓存，APK带附件及长期缓存头。根路径HEAD的403是OSS静态首页行为，不用它判断页面不可访问。
- 发布时发现公开URL中的 `+` 被OSS转为空格；已改为连字符，补旧URL修复回归并重新发布同一安装包。
- 首次上线复用受授权的本地生产OSS配置执行SDK，凭据未打印或提交；CI后续采用GitHub production中的专用发布账号。浏览器上传工具对本工作区文件误报目录不可访问，未通过路径绕过处理。
- 当前为 Gate 2 待验收，不能将本地回归/首次SDK发布等同于合入main后的Actions端到端验证。

## 备注

- 已知应用 ID：`com.duxue.app`；包内 API 为 `https://duxuelai.xyz/api`。现有 APK 只发布到 Actions Artifact，不能直接作为匿名公开下载地址。
- 用户确认 Bucket 位于北京，Endpoint 为 `oss-cn-beijing.aliyuncs.com`，域名为 `download.duxuelai.xyz`。
- 用户确认尚未上架 iOS 和安卓商店，首版只提供 APK，iOS 暂未开放。
- GitHub production Environment 已有 App 签名凭据的配置约定，无需用户重新提供签名材料；不要求用户在对话发送 AccessKey Secret。
- 云端配置进度与验证证据统一记录于 [部署文档](../../docs/deployment.md#下载页基础设施)，不在本文件复制。
