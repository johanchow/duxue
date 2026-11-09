---
slug: tutoring-agent-admin
status: review
---
# Tutoring配置管理台

用户已确认Next.js全栈、独立测试数据库、30秒发布拉取、独立管理员、真实隔离调试及只读流程，并要求实施和调试至成功；Gate 1已确认。

## 验收标准
- [x] duxue-admin独立Next.js应用、独立管理员与HttpOnly会话；所有管理/内部API校验权限。
- [x] PostgreSQL迁移包含用户/会话、乐观锁草稿、不可变发布、环境指针、加载回执、调试及审计；只用duxue-admin-test。
- [x] 可编辑受限配置、查看差异/只读协议与流程、Python权威校验、真实隔离调试、查看调用步骤及用量。
- [x] 完整配置包原子发布与回滚；发布校验和调试绑定精确草稿revision/digest；服务端30秒拉取并固定单轮配置，失败保留旧版。
- [x] 测试覆盖鉴权、不可变/并发/旧版本、配置隔离、真实HTTP端到端；浏览器实测与实际模型调试成功。
- [x] 文档/笔记、全量回归和构建通过，保留证据。
- [ ] Gate 2：用户验收；未宣称已人工验收。

## 实现计划
Next.js App Router+pg SQL迁移；复用参考界面结构，管理数据真实存库。duxue-server提供内部鉴权catalog/validate/debug，隔离进程运行同源无数据库副作用答疑；ContextVar隔离发布配置，后台轮询/本地最后成功快照。测试与生产数据库分开，仅配置测试环境；无流程编辑、无生产发布、无跨环境隐式推送。

## 清单
- [x] 数据设计与数据库
- [x] 服务端快照/校验/隔离调试/拉取
- [x] Next.js界面/API
- [x] 自动与浏览器/真实模型验证
- [x] 文档/笔记

## 验证记录（2026-11-08）

- 服务端全量：836 passed、1 skipped、3 subtests passed（24.33s）；新增管理台快照/权限/题面传递测试6通过。
- 管理台：3项认证/真实PostgreSQL约束测试通过，TypeScript检查、Next.js生产构建通过；Python新增文件Ruff及改动适配文件F/E9/I检查通过，git diff --check通过。
- HTTP回归：未登录/内部密钥拒绝、CSRF、并发保存200/409、协议修改422、缺精确调试证据不能发布、当前发布指针不变均通过。
- 浏览器：真实登录→新建/编辑/保存→校验→受保护数学题真实导师/Judge→发布→实例loaded→回滚通过；桌面/手机无横向溢出，基线差异重载后仍在，流程节点与边只读。
- 真实模型题目为3盒彩笔、每盒4支；导师围绕题面给加法/乘法提示，无最终答案，独立Judge通过；记录2次模型调用及真实Token。R3加载后回滚R1，服务实例重启后从缓存/拉取恢复R1。
- 实际数据库为duxue-admin-test，001至004迁移已应用；未启用生产。运行地址http://127.0.0.1:3021，既有Python代码本地实例8011；账号凭据在ignored `.local/bootstrap.json`。
- 本机证据：`duxue-admin/.local/verification.json`、overview-final.png、config-debug.png、mobile.png、flows.png；不提交私有凭据与运行记录。原静态运营页保留在public/legacy。
- 调试只支持文字/人工题面，无真实业务会话写入；图片上传、多轮回放与生产发布不属于本期。代码未提交/未线上部署。

## Gate 2反馈修复：Agent目录与Workflow可视化

用户指出缺少系统Agent数量/作用，以及真正的Node/Edge图与配置查看，已明确要求补齐，沿用原只读流程范围，无新增流程编辑。

- [x] 服务端返回全部已登记Agent、中文作用、模型/代码分类、所属Workflow和原始组件定义；计数不硬编码。
- [x] 管理台总览/独立Agent目录、搜索、配置查看与Workflow跳转。
- [x] 真实拓扑图保留条件分支/平行边/循环；parent关系单独表示；节点/边/完整Workflow配置均可查看。
- [x] 新增回归、浏览器点击与最终构建验证。

反馈修复验证：服务端837 passed、1 skipped、3 subtests passed；管理台13项测试、TypeScript与生产构建通过。浏览器逐一验证9个流程、所有节点/控制边数量、Agent搜索/配置跳转、节点与两条平行边点击、完整JSON相等、移动端无溢出。截图保留在ignored `.local/agent-inventory.png`、workflow-vet.png、workflow-tutoring.png、workflow-mobile.png。

## Gate 2反馈：表格列表、独立详情与入口职责

用户要求Workflow/Agent改table，点击进入详情，流程节点按真实代码实现展示，并澄清配置工作台职责；按原只读流程及Tutoring编辑发布范围实施。

- [x] Agent和Workflow表格显示动态总数、摘要和详情入口。
- [x] 独立URL详情、直接打开/刷新/返回列表；Agent完整配置展示与草稿编辑保存后恢复。
- [x] 节点区分模型Agent、代码Agent、Judge/代码Gate和固定代码Action；保留真实回路，不冒充无环DAG。
- [x] 移除“配置工作台”命名，Agent详情承接单Agent编辑，“配置草稿”管理同一完整包的依赖/校验/调试/发布。
- [x] 新增路由与节点类型回归，管理台15测试通过；浏览器遍历9流程URL、表格数量、节点/边查看、完整JSON、Agent保存/刷新/草稿联动/校验、只读代码Agent、移动端均通过。
- [x] 最终生产构建与文档审阅。

证据：ignored `.local/workflow-table.png`、agent-table.png、workflow-detail.png、agent-detail-edit.png、workflow-table-mobile.png；测试入口`npm run test:inventory`。

## Gate 2反馈：组件类型、流程简介与发布入口合并

- [x] Workflow在Agent菜单上方，列表移除入口/处理器/Node/Edge，新增唯一元数据来源的简介。
- [x] 组件列表涵盖全部Agent/Gate/Tool，分五类筛选，分类数量及作用准确；保留原agents接口语义。
- [x] 已接入的Tutoring Judge与静态工具也支持详情配置编辑/保存/权威校验，固定代码和未接入组件不伪装可编辑。
- [x] 移除配置草稿菜单，将其列表并入发布与回滚；保留同一完整包的草稿/校验/调试/发布协议。
- [x] 浏览器全组件/筛选/实际保存验证与最终构建；设计/笔记同步。

本轮：服务端838 passed、1 skipped、3 subtests passed；管理台15测试、类型/生产构建/Ruff通过。浏览器验证25组件完整定义、五类型数量、Workflow简介表头、菜单顺序、无独立草稿菜单、导师/Judge/静态Tool实际编辑保存与Python校验、发布页草稿列表、移动端。未调用模型/发布测试修改。

## 用户明确扩展：Admin完整产物优先、全部组件配置编辑发布

- [x] format_version=2包含全部35份JSON，从产物建完整运行目录；旧v1不隐式补包，历史保留且明确不兼容。
- [x] 全部模型Agent/Judge可编辑模型/Prompt/片段/已授权工具；所有代码组件可编辑展示元数据，固定Python/协议/安全字段仍受保护。
- [x] 非Tutoring运行路径优先读取发布快照，计划/任务动态Prompt不再读启动缓存，应用入口与嵌套调用固定同一版本；Admin无兼容发布时拒绝默认执行。
- [x] UI默认展示Admin发布值/来源版本；通用真实模型调试及发布覆盖校验，任意模型单元变更需对应同修订调试。
- [x] 真实意图模型调试/发布R4/35文件加载回执/重启恢复通过；服务端844通过、1跳过，管理台16测试、类型/生产构建通过。
- [x] 最终浏览器/HTTP回归与文档审阅。

浏览器已遍历25组件、实际编辑导师/Judge/工具正文及代码组件名称；HTTP鉴权/CSRF/并发保存/协议保护/无调试拒绝发布通过。R4重启恢复与Admin来源回执通过，旧发布保留并标注不兼容，不篡改历史。

旧版首期范围记录为历史，不再作为当前只读/发布边界；唯一当前设计见design-admin.md。

最终补充：备用网关复用时按当前固定快照重新解析模型，不缓存旧spec，新增先红后绿回归。真实浏览器R5发布/加载/回滚R4通过，当前指针R4；最终服务端844 passed、1 skipped、3 subtests passed。

## UI与单草稿收敛（用户确认）

- [x] 首页Workflow；主导航Workflow/Agent/发布管理，调试记录次级；移除工作概览、通用说明和操作审计页面，后台审计保留。
- [x] 内容操作按钮右侧；Agent编辑在页标题右上角，单组件移除冗余文件侧栏；统一发布入口与版本详情。
- [x] 005迁移约束每环境最多1份working草稿，接口幂等获取、所有组件共享；发布/放弃后只读归档，原revision仅并发号；保留历史证据。
- [x] 服务端加载状态收敛到发布管理；调试表格显示对象ID/类型/发布基线/快照/结果与实际步骤，未知历史不猜测。
- [x] 最终实际发布/回滚、自动检查、浏览器与文档验证。

17项管理台测试、类型/生产构建通过；005已应用duxue-admin-test。浏览器验证单草稿跨组件、右上编辑、版本详情、调试目标、移动端，并真实调试/发布R6与R7/加载/最终回滚R4。跳转成功反馈与测试导航选择器已修复，续验后半发布回执/回滚通过。截图在ignored `.local/publication-manager.png`、debug-records.png、agent-detail-edit.png、mobile.png。


## 版本身份与发布证据收敛（2026-11-09，用户明确无需兼容旧数据）

- [x] Agent/Workflow页不显示组件v号或当前发布R号，仅在组件有修改时标识；R历史留在统一发布管理。
- [x] 格式3产物不含组件/模型手工version，Prompt/片段ID稳定；内部运行身份统一使用包digest，代码默认值旧version变化不改变Admin契约摘要。只接收格式3，无旧数据转换。
- [x] 006迁移已在测试库应用；纯名称/简介发布无需模型调用，debug_run_id允许为空；禁止已有发布时无改动重复发布。
- [x] 调试覆盖精确component_id；备用改动不能由主模型替代，共用Prompt/工具变动覆盖所有相关模型。
- [x] 发布管理“查看变更”直达完整差异；校验结束写回仅允许working草稿，避免并发放弃后更新。
- [x] 真实非答疑调试/发布R8/加载，纯元数据免模型发布R9，主模型证据不能替代备用→实际备用调试→R10发布→回滚R9，均通过。证据在ignored `.local/full-release-smoke.json` 与 `.local/publication-identity.json`。
- [x] 服务端845 passed、1 skipped、3 subtests；管理台19项测试、类型/构建、HTTP权限/并发/协议/覆盖/禁止空发布、浏览器全目录/详情/草稿标识/编辑/移动端通过。
- [x] 当前技术设计与后续改进已更新；未提交、未部署生产。

旧节为历史验证记录；当前设计唯一事实源为[管理台设计](../../docs/technical/design-admin.md)。Gate 2仍待用户验收。

## 用户新增角色要求（2026-11-09）

用户明确要求实现visitor/admin，沿用现有管理台spec与已授权实施范围。计划：007迁移角色约束（现有账号admin，新账号默认visitor）；会话每请求读角色，API统一拒绝visitor配置写操作；visitor可调试已有草稿或不可变发布，不创建草稿；UI移除修改/发布/回滚入口，CLI支持角色创建/调整。测试覆盖数据库约束、接口越权/降权即时生效、visitor发布包调试及页面权限，更新设计/笔记。

- [x] 数据库/会话/CLI角色
- [x] API强制权限与独立发布包调试
- [x] UI只读浏览与可调试
- [x] 权限回归、构建、浏览器与文档

角色验证：007已应用duxue-admin-test；21项Node/真实PG测试、类型检查/构建、原HTTP权限/并发/发布门禁与管理员目录浏览器回归通过。独立访客浏览器真实意图模型调试通过，发布快照/草稿数与修订/环境指针不变；访客无编辑/保存/发布/回滚入口，手动写接口403，草稿只读及产物下载可用。真实调试测试账号结束后停用，保留审计引用；截图ignored `.local/visitor-debug.png`。角色升降由CLI维护，不增加未要求的用户管理菜单；生产未操作。

## 用户确认调试优化（2026-11-09）

按已确认建议实施第一阶段：正常Agent/Workflow详情默认已发布，草稿页默认已保存完整草稿，未保存禁止调试；Agent锁定当前对象，仅允许自身主备模型。Workflow新增真实隔离执行入口，先接入完整Tutoring及已有无副作用单Agent流程，未接入明确不可用；不新增流程编辑。通过执行器及现有业务观测采集Node输入/输出、条件边与重试，不根据静态图伪造经过路径。保留失败步骤与精确快照身份，旧调试脚本只作为接口回归。

- [x] 调试契约/能力目录、隔离执行与失败追踪
- [x] 来源快照持久化及服务端目标校验
- [x] Agent固定目标/Workflow调试/节点检查界面
- [x] 回归、真实模型与浏览器验证、文档笔记

本轮结果：008已应用测试库，完整debug bundle/source/target持久保存；调试页发布/草稿来源明确、图与执行保持同一快照，单Agent仅本对象主备模型，服务端拒绝跨对象模型。5个Workflow接入生产入口（Tutoring/Reflection使用独立内存业务库，其他3个为现有无持久化服务），代码Agent支持自身Tutoring/Reflection实现；协调器/Planning单独调试明确未接入，审核/重试子流程随Tutoring留痕。ContextVar可选执行追踪记录Node、实际条件/边、输入/输出、模型原始/校验结果、重试及失败，未走分支不伪造。

验证：服务端851 passed、1 skipped、3 subtests，追加自述写入投影后6项目标回归通过；管理台22项测试/类型/构建、原HTTP回归、全组件浏览器与visitor真实模型调试通过。新浏览器脚本真实执行已发布意图Agent、已发布原话总结Workflow、已保存Reflection草稿及受保护Tutor完整Workflow，验证无跨Agent选择、未保存禁调试、节点/边查看、无关代码Gate不可用；发布指针和草稿修订未改变。HTTP额外验证Reflection确认分支（0模型）写入仅在可销毁库。截图/调试ID在ignored `.local/workflow-debug-nodes.png`、tutoring-debug-nodes.png、debugging-verification.json。Ruff新文件完整与适配文件F/E9/I、git diff --check通过。未新增流程编辑，未提交/生产部署。图片、取消、批量评测/自动版本对比不属于本阶段，当前事实见管理台设计。

## 调试交互反馈（2026-11-09）

用户指出未接入提示缺少具体原因，以及调试输入位于长页面底部。沿用已有优化授权：Agent/Workflow/完整草稿统一右侧原生dialog抽屉，点击即打开、独立滚动、Escape/关闭返回原处，同一快照重开保留输入/结果；Workflow结果可返回图检查节点。未接入对象在入口处说明具体依赖，并提供已有所属Workflow跳转，不新增执行适配器范围。仅改UI/能力提示，发布来源和visitor权限不变。测试覆盖能力判断、抽屉打开/焦点/关闭重开/移动端、未保存草稿及流程检查返回，更新文档笔记。
- [x] 抽屉入口与状态保留
- [x] 未接入原因与所属Workflow定位
- [x] UI回归/构建与文档

本轮验证：23项管理台测试、类型/生产构建通过；抽屉浏览器验证打开即见输入/自动焦点、背景锁滚动、焦点返回、Escape、同快照输入/结果保留、未保存禁调试、Reflection真实执行后返回Node检查、未接入Gate跳转所属Workflow、390px移动端无溢出。原全目录与visitor真实意图模型/权限浏览器回归通过。截图ignored `.local/debug-drawer-agent.png`、debug-drawer-mobile.png已目视检查；发布指针/草稿修订不变，无后端执行逻辑/数据库迁移变动。具体界面事实源见管理台设计。

## 用户确认正式域名与Docker自动部署（2026-11-09）

用户确认admin.duxuelai.xyz、与Server同台ECS、Docker、main变更自动部署，并提供仓库忽略的ali-ecs.pem。已授权正式站点实施，延续已有管理员/角色与配置发布边界。计划：test/prod独立DB与动态环境指针；Next独立Docker镜像与只在私有网络暴露的Python控制执行镜像；复用production GitHub凭据构建/部署；独立Nginx/HTTPS/自动续期；正式库迁移和独立初始化账号；HTTP/权限/真实调试/回滚验证。现有业务API的运行配置来源不随本次站点上线自动切换。DNS需用户在阿里云添加admin A 47.107.176.107，异步等待，期间先完成代码与ECS准备。
- [x] 正式环境/数据库与隔离控制入口
- [x] Docker/自动部署/HTTPS配置与测试（首次证书仍待DNS）
- [x] ECS容器、正式库、独立管理员、登录/CSRF/模型/Workflow/发布/回滚验证
- [x] DNS解析、首次HTTPS证书与公网浏览器验证
- [x] 文档/笔记/最终审阅（域名验收仍待DNS）

正式上线阶段结果（DNS待用户添加）：ECS上Admin/私有executor均healthy，Node仅绑定127.0.0.1:3021，executor没有宿主端口及业务DB/Redis/OSS凭据；duxue-admin-prod空库已迁移001–009，独立admin账号已创建。真实意图模型通过后初始化发布R1（35文件），发布快照的Reflection确认在内存库通过，跨站403/未登录401/安全Cookie及正式指针并发回滚校验通过，最终仍R1。既有公网API健康200；本次未更新现有业务API容器或其配置来源。正式凭据在ignored `.local/production-bootstrap.json`（0600），不写入仓库。

Node26测试/类型/生产构建、Python852通过/1跳过/3 subtests、原浏览器全目录通过。Docker现场暴露并修复CLI依赖未被Next standalone复制的问题：迁移工具改为自包含CommonJS包，async main避免顶层await，实际正式库迁移已通过。本机setup禁止prod并有不连接DB的子进程回归。ECS无法连接Docker Hub，经Docker官方ECR Node镜像完成同版本首次构建；后续GitHub构建推GHCR，ECS只拉成品。证书工具/HTTP验证站点/续期timer和Nginx reload hook已准备，DNS目前仍NXDOMAIN，没有宣称域名或TLS可用。测试/正式库与环境选择、无公网执行端口/内部发布接口拒绝等均有回归。

待完成：阿里云admin A指向47.107.176.107后签发/安装证书并验证HTTPS；合入main才会激活新增自动部署工作流（本分支准备审阅，不擅自合并触发现有Server部署）。当前操作流程唯一说明见部署文档。

现场运维补充：apt安装certbot时Ubuntu needrestart自动重启docker.service，Worker/Beat容器重启，API仍健康；已核对内核无OOM。部署文档的首次安装命令改为NEEDRESTART_MODE=l，仅列出待重启服务，避免包安装隐式重启Docker。

只读核对Worker日志：Redis invalid password从2026-11-08 12:42:49 UTC持续存在，早于本次部署，Worker/Beat已有21次重启；不能将容器Up视为业务恢复。本次未改其配置，需另行修复Redis凭据。API仍健康。临时远端初始化凭据文件已删除，本机0600凭据文件保留。

2026-11-09 用户明确暂不提交/推送/合并代码，只完成域名/Docker/ECS。经Chrome DevTools MCP在用户登录后的阿里云控制台新增admin A 47.107.176.107（默认线路、TTL10分钟），公共DNS/ECS解析通过。Let’s Encrypt独立证书已签发安装至Nginx，有效期至2027-02-07；renew dry-run含deploy hook成功，timer active。公网HTTPS health200、HTTP301、internal release404、既有API200；Chrome实际正式管理员登录、Workflow/Agent与35文件目录通过。浏览器保留已登录正式站点。未提交、推送或合并，自动发布仍待用户后续合main。上述DNS待办历史现已解决。

## 用户要求简化本地环境（2026-11-09）

统一读取duxue-admin/.env并显式提供数据库连接，不再读取.env.local、模板或Server环境兜底；setup不自动生成隐式连接。一次迁移原有私密参数并删除旧文件，本地执行器改用已有隔离控制入口且仅加载Admin环境；正式ECS环境不改。本轮先补Node配置回归，确认旧实现两项失败后修复，补Python隔离环境测试。验收进行中。

本轮验收完成：28项Node测试、类型检查/生产构建、2项Python环境/入口测试、Ruff与diff检查通过。实际setup连接显式测试库成功；本地Next输出Environments: .env，隔离执行器与Next已重启；真实已发布意图Agent调用成功、35文件目录正常，发布指针/代次未改变。新.env权限0600并被Git忽略，无凭据输出；线上环境未操作。

## 本地提交准备（2026-11-09）

用户要求将当前Agent Studio、配置JSON扩展、隔离调试、本地.env简化、Docker自动部署定义及现场运维文档提交到codex/admin-production-deploy，暂不push。当前代码验证为Node28项、类型/构建、Server853通过/1跳过/3 subtests，真实本地调试及正式HTTPS验证通过；Redis恢复与队列迁移结果已写入部署文档/平台笔记。提交前统一审阅暂存区，排除所有环境文件、pem、账号凭据和本地运行产物。
