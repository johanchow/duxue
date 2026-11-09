# 读学 Agent Studio

Next.js全栈的Agent配置管理台。数据表、发布协议和边界的唯一说明见[管理台设计](../docs/technical/design-admin.md)。支持测试/正式环境独立数据库与Docker部署；Workflow保持只读，不支持流程编排。

## 本机启动

```bash
cd duxue-admin
nvm use
npm ci
# 先在本目录 .env 中填写以下连接参数
npm run setup
# 分别在两个终端启动
npm run server:dev
npm run dev
```

管理台：<http://127.0.0.1:3021>。`server:dev`启动复用`duxue-server`代码的隔离调试执行器（8011端口），不启动业务API或配置拉取，不连接业务数据库/Redis。管理台后端全部在Next.js中。

本地环境参数只在 `duxue-admin/.env` 维护，Next.js、CLI和本地Python执行器均读取这一个文件；不读取`.env.local`、模板或相邻Server的环境文件。文件不提交Git。至少配置：

```dotenv
ADMIN_ENV=test
ADMIN_DATABASE_URL=postgresql://用户名:密码@数据库主机:5432/duxue-admin-test
AGENT_SERVER_URL=http://127.0.0.1:8011
AGENT_ADMIN_INTERNAL_TOKEN=至少32字符的随机共享密钥
VLM_API_KEY=模型服务密钥
```

`setup`只创建/迁移`duxue-admin-test`，要求显式配置`ADMIN_DATABASE_URL`，不会自动生成环境文件或从其他项目推导连接。独立admin账号的登录信息保存在`.local/bootstrap.json`（权限0600，不提交）；重复初始化不会重置密码。已有管理员与本地凭据不匹配时会报错。可用`ADMIN_INIT_EMAIL`和`ADMIN_INIT_PASSWORD`控制首次初始化账号。修改`.env`后重启本地服务；已有进程环境变量优先，便于CI/Docker注入。

本机Rosetta环境如无法加载已有arm64 Python扩展，可在`.env`设置`DUXUE_PYTHON_ARCH=arm64`；仍使用仓库原虚拟环境。Linux不需要此项。所有Node命令先执行`nvm use`，避免系统旧Node被误用。

## 独立部署测试环境

- Next.js：`ADMIN_ENV=test`，`ADMIN_DATABASE_URL`（实际库名强制`duxue-admin-test`），`AGENT_SERVER_URL`，`AGENT_ADMIN_INTERNAL_TOKEN`，对外HTTPS地址`ADMIN_PUBLIC_ORIGIN`。
- 现有Python服务：同一个`AGENT_ADMIN_INTERNAL_TOKEN`，`AGENT_CONFIG_SOURCE=admin`、私有`AGENT_CONFIG_SOURCE_URL`（不走公网Nginx），持久目录`AGENT_CONFIG_CACHE`；APP_ENV为test。
- 使用`npm run build && npm start`运行Node服务；反向代理请求超时至少300秒。不要部署成纯静态站点，也不要使用短时限的无状态函数执行调试请求。
- 服务端与管理台密钥通过私有环境变量配置，不使用`NEXT_PUBLIC_*`。DB连接无需在浏览器配置。正式环境使用`ADMIN_ENV=prod`与独立`duxue-admin-prod`；部署步骤见[部署文档](../docs/deployment.md#admin正式站点)。

## 使用

首页直接进入Workflow；主要菜单为Workflow、Agent、发布管理，另有调试记录。操作按钮统一在右侧，Agent编辑在详情页右上角。当前环境只有一份共享待发布草稿，修改不同组件会汇总到同一配置包；发布/放弃后才开始下一份。服务端同步状态在发布管理按需展开。操作审计页面移除，后台审计仍保留。

“Workflow”(`/workflows`)提供真实流程图与完整只读配置；“Agent”(`/agents`)展示全部Agent/Gate/Tool，搜索与类型筛选并排。详情默认显示当前Admin发布值，仅标识有待发布修改，所有组件支持编辑；模型Agent/Judge可改模型与Prompt，工具可改描述/静态正文，固定Python实现与安全协议受保护。待发布修改和历史统一在“发布管理”，无独立草稿菜单。

服务端优先运行Admin完整发布产物（format_version=3，35份JSON），30秒拉取并按应用调用固定快照。Admin模式无兼容发布/缓存时AI调用报配置未就绪，不静默使用代码默认值。本地使用显式导出快照；不再存在仓库业务默认模式。Workflow完整JSON也仅来自Admin，Server不保留流程副本；流程仍只读，保存/发布接口会拒绝流程修改。不支持旧协议加载或数据转换。发布产物无组件手工v号，内部身份由包digest生成；R序号仅在发布管理/历史展示。

Agent详情只调试当前Agent；主备仅限自身模型，动态Prompt输入模板变量JSON。Workflow详情可调试已发布配置或已有已保存草稿；未保存修改禁止调试。完整草稿页可集中选择对象。当前接入的流程及限制见管理台设计。修改模型后，必须实际调试对应的主/备component；共享Prompt变动要覆盖两者。仅改名称/简介无需调用模型；已有发布且无修改时不能重复发布。真实联调脚本`npx tsx scripts/full-release-smoke.ts`会调用导师和意图模型、校验覆盖门禁并发布测试完整包，需要已启动两个服务，会产生真实用量和测试记录。


## 验证

```bash
npm test                 # 认证与真实PostgreSQL约束；数据在事务内隔离并回滚
npm run typecheck
npm run build
# 以下需要上述两项服务已启动，会创建测试草稿/记录并消耗真实模型用量
npm run test:smoke       # 登录/校验/真实模型/发布
npm run test:browser     # 独立浏览器端到端，含发布和回滚
npm run test:inventory   # 表格/详情深链接、节点/连线、保存刷新、完整配置包校验
```

浏览器测试默认使用本机Chrome，其他安装路径用`CHROME_PATH`指定。凭据及截图/联调证据保留在ignored `.local/`。`scripts/api-check.ts`可验证鉴权、CSRF、并发保存、协议只读、模型改动无调试不能发布及禁止空发布，不调用真实模型。

`npx tsx scripts/publication-identity-smoke.ts`验证纯展示修改免模型发布、备用模型精确调试门禁及发布后回滚；会调用真实模型并创建测试记录。

## 账号角色

`visitor`可查看、下载、调试已发布配置和已有工作草稿；不能新建/保存/校验/放弃配置，也不能发布或回滚。`admin`可执行全部受控操作。现有账号保持admin，新用户默认visitor；每次请求重新读取角色，调整后旧会话立即受限。Agent/Workflow详情的“调试已发布配置”不需要创建草稿。

通过私有环境变量提供`ADMIN_INIT_EMAIL`、`ADMIN_INIT_PASSWORD`，执行`npm run user:create`创建visitor；显式`ADMIN_INIT_ROLE=admin`可创建admin。设置`ADMIN_INIT_EMAIL`及`ADMIN_INIT_ROLE=visitor`或`admin`，执行`npm run user:role`调整已有账号角色。密码至少14位，不提供网页自注册/角色提升接口。`npm run setup`只初始化独立管理员，不会重置已有密码/角色。

`npx tsx scripts/visitor-smoke.ts`验证visitor只读页面、已有草稿浏览、真实发布模型调试、下载入口与越权拒绝，会产生真实模型用量；测试账号结束后停用，保留审计关联。

`npx tsx scripts/debugging-smoke.ts`验证Agent固定目标、已发布/草稿来源、未保存拦截、真实Workflow运行、图中Node/Edge数据和未接入组件提示。会产生真实模型用量，截图/记录在ignored `.local/`；不发布配置。

调试入口位于详情/编辑页顶部，点击打开右侧抽屉；手机全屏。关闭后同一快照保留输入和结果，Workflow运行完成后可点“查看流程执行”返回图。尚未接入独立调试的组件显示具体原因及所属Workflow入口。`npx tsx scripts/debug-drawer-browser.ts`验证焦点/滚动、重开保留、草稿未保存拦截、移动端与流程返回；仅执行一次无模型调用的Reflection测试，不发布或修改配置。

## 配置快照导入导出

已有环境从数据库管理当前发布/唯一草稿，目录不依赖Server默认JSON。空管理库需先`npm run setup`初始化账号，再由管理员导入已有Admin备份；导入不自动发布、不覆盖已有发布或草稿：

```bash
ADMIN_INIT_EMAIL=<管理员邮箱> npm run config:import -- /path/admin-release.json
# 在页面调试并发布后，导出完整不可变发布身份和产物：
npm run config:export -- ../duxue-server/var/admin/release.json
# 另存当前已保存草稿，用于离线实验：
npm run config:export -- ../duxue-server/var/admin/candidate.json --draft
```

导出目标必须不存在，避免误覆盖已用于评测的快照。普通用户也可在“发布管理→版本详情→下载配置快照”下载指定发布；GET `/api/drafts/<id>/snapshot`导出已保存草稿，不包含编辑器未保存内容。快照包含`id/digest/bundle`及release/draft身份；CLI从管理库读取，Python校验权威契约。文件与模型密钥、数据库凭据分开，不进入Git。离线运行参数见[Server配置入口](../duxue-server/agent_specs/README.md#本地与离线评测)。

`npx tsx scripts/config-snapshot-smoke.ts`在测试管理库临时schema验证空库无默认值、CLI导入导出、页面快照下载及禁止覆盖，需本地执行器已启动，不发布或修改原环境指针。
