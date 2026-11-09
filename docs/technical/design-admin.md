# Agent 配置管理台设计

状态：Next.js/React全栈管理台与Python运行端已实现并完成真实联调，支持test/prod独立配置数据库及Docker部署。管理台在`duxue-admin/`，执行代码仍在`duxue-server/`。不做流程编排。正式域名与操作步骤见[部署文档](../deployment.md#admin正式站点)；当前上线验收进度见[spec](../../.agent/specs/tutoring-agent-admin.md)。

## 一、配置事实源与职责

**Admin不可变发布产物是已接入服务实例的运行配置主来源。** Git拥有执行代码、授权范围、安全基线、输入输出协议与代码契约；Admin数据库拥有草稿、完整发布包与环境指针；服务端缓存与离线导出只是Admin快照的副本。启用Admin模式后，不从代码默认值补齐缺失组件。

Next.js负责独立账号认证与角色授权、配置生命周期、审计、发布/回滚及加载回执；Python负责权威契约校验、真实隔离调试和运行快照。没有另一套管理台FastAPI后端，也不在JS重写业务执行逻辑。界面默认读取当前Admin发布配置；Agent/Workflow页不显示发布版本，仅在组件有待发布修改时显示标识。R序号只在统一发布管理和发布历史中展示。尚无发布时显示已导入草稿；空库明确提示导入配置快照，不自动构造业务默认值。

`ADMIN_ENV=test`使用`duxue-admin-test`，本机可复用`duxue-server/.env`连接参数；`ADMIN_ENV=prod`使用独立`duxue-admin-prod`，必须显式提供`ADMIN_DATABASE_URL`与HTTPS `ADMIN_PUBLIC_ORIGIN`。数据库名由环境固定，不能靠URL路径切到业务库或另一个环境。每个数据库只有一条环境指针，不共享测试/正式草稿、账号或发布记录。

角色仅管理台账号使用，不改变App的Ward/Guardian等业务角色。`admin`可查看、调试及受控编辑/校验/放弃/发布/回滚；`visitor`仅查看、下载和调试，不能创建或修改任何配置。鉴权每次请求读取数据库role与active，降权/停用不等旧会话过期；写接口默认拒绝visitor，只明确允许调试和退出登录。UI隐藏所有配置写入口，直接打开草稿也是只读展示。角色由受控CLI管理，不增加用户管理菜单。

发布产物的持久事实源是`agent_releases.bundle`（PostgreSQL JSONB），不是Admin磁盘目录或Git文件。`agent_environments.release_id`指向生效记录，`GET /api/releases/<id>`下载名为`agents-R<sequence>.json`的完整包。其结构为：

```json
{
  "format_version": 3,
  "compatibility": "受代码保护契约的SHA-256",
  "files": {
    "agents/tutoring.turn.json": { "id": "tutoring.turn", "kind": "agent", "…": "完整定义" },
    "gates/tutoring.leak-judge.json": { "…": "完整定义" },
    "tools/tutoring.widget_guidelines.json": { "…": "完整定义" },
    "workflows/tutoring.json": { "…": "完整定义" },
    "schemas/agent-result.json": { "…": "完整协议" }
  }
}
```

上面仅为结构示意，实际files包含下述35份完整JSON。发布记录另外保存id、sequence、digest、validation与发布人/时间；digest覆盖整个bundle，与compatibility的含义不同。Python本机缓存默认`duxue-server/var/admin/last-good.json`，可由`AGENT_CONFIG_CACHE`指定；它保存发布ID/digest/bundle，是恢复副本。

## 二、完整产物与编辑边界

产物`format_version=3`包含35份完整逻辑JSON文件：10个Agent、11个Gate、4个Tool、9个只读Workflow及1份统一结果协议。文件白名单和代码兼容性摘要随包保存；服务端验证完整性、摘要、固定契约及注册处理器后，从产物本身构建运行目录，不再复制本地默认JSON填充运行值。

| 对象 | Admin允许编辑 | 受代码保护 |
|---|---|---|
| 全部7个模型Agent、3个模型Judge | 显示名称/简介、主备模型参数、主Prompt、既有片段正文、已授权工具的子集 | ID、协议、变量绑定、上下文构造器、权限上限、Judge失败策略 |
| 静态Tool | 显示名称/简介、静态正文 | 参数/结果Schema、处理器与读写权限 |
| 动态Tool、3个代码Agent、8个代码Gate | 显示名称/简介，随发布包生效 | 固定Python实现、处理器、输入输出协议、安全与事务规则 |
| Workflow和统一结果协议 | 查看完整配置 | 拓扑、必经门禁、循环预算、输出协议，不提供流程编辑 |

因此组件不再整页只读，但Admin不是Python在线代码编辑器。名称/简介字段`display_name`、`description`可选；没有填写时，管理目录用`inventory.py`中的展示元数据。默认Prompt和模型初始化仍在Git JSON中，在线编辑后以发布值为准。启用快照时，环境变量`AI_MODEL_OVERRIDES`不再覆盖所选模型。

产物不包含组件/模型手工`version`，Prompt与片段ID保持稳定。运行目录所需的内部版本和观测身份统一由完整包digest生成；改代码默认文件里的旧版本号不会导致Admin发布失效。协议Schema ID和提供商模型名称中的版本仍有各自语义。固定契约摘要只绑定受保护的字段/注册表，编辑Prompt等运行值不会改变契约摘要。

仅接受格式3，不提供旧数据转换或旧协议兼容加载。006迁移归档旧格式工作草稿并清空旧格式环境指针；旧数据库行无需转换，当前列表仅查询新格式。初始化使用当前服务端导出的完整包；Admin模式无有效发布/缓存时AI明确不可用。

## 三、数据表与并发

SQL在`duxue-admin/migrations/`；`admin_schema_migrations`记录001至009迁移，事务与advisory lock串行执行。005迁移增加草稿状态/单工作草稿索引，以及调试发生时的发布基线引用；006迁移切换格式3，并允许纯展示元数据发布的debug_run_id为空；007增加用户role，原有账号为admin，新账号默认visitor；008保存调试source_kind、target_kind/target_id和完整bundle快照；009允许test/prod合法环境并限制每库只有一条环境记录，迁移工具根据已校验的环境设置指针名称。

| 表 | 关键约束与职责 |
|---|---|
| `admin_users` | 唯一邮箱、scrypt密码摘要、active、role（visitor/admin）；只由CLI创建/调整角色，无注册 |
| `admin_sessions` | 仅保存Token摘要、12小时过期；HttpOnly/SameSite=Strict Cookie |
| `admin_login_attempts` | 同邮箱15分钟最多10次登录尝试 |
| `agent_drafts` | 同一环境仅一份working草稿（partial unique index）；POST编辑入口在事务/advisory lock下获取或创建同一份。完整bundle JSONB、revision仅用于并发与调试证据，不是多个可选草稿版本；base_bundle/base_release_id持久记录创建基线。发布后state=published，放弃时archived，历史FK保留 |
| `agent_debug_runs` | 绑定draft/revision/digest及实际输入、组件、结果、模型步骤与用量，创建时记录base_release_id、来源类型、目标类型/ID和完整bundle；后续草稿修改不会改变调试快照。结果包含执行代码摘要，历史未知基线不猜测；每管理员一个running；超10分钟显示interrupted |
| `agent_releases` | 不可变完整快照、唯一序号；trigger拒绝更新/删除；复合FK将调试证据绑定精确draft/revision/digest |
| `agent_environments` | 当前release指针及generation，行锁比较并原子更新；按环境固定test/prod |
| `agent_server_instances` | 实例实际release/digest、加载结果及心跳，90秒内视为在线 |
| `admin_audit` | 登录、修改、调试、发布和回滚审计，不保存密码与共享密钥 |

发布需Python重新校验并锁定草稿和环境，检查working状态、revision/generation、创建基线是否仍为当前发布及同摘要成功调试。当前发布变化时，不允许悄悄覆盖；需先整理并重新编辑。调试要求精确到实际模型`component_id`：单独修改备用模型时，主模型成功不能替代备用模型；共用Prompt、片段或工具绑定变化时，主备均需通过；静态工具正文变化需覆盖实际消费该工具的各模型。`covered_components`只能来自实际成功调用步骤。只改名称/简介不调用模型即可发布，debug_run_id为空；已有发布且完整包没有变化时拒绝重复发布。首次初始化可发布基线包。

## 四、加载、固定快照与恢复

生产API与Celery子进程在显式Admin模式每30秒拉取完整发布包，验证prod环境、完整性、兼容性及digest，原子持久化后切换指针并回执。缓存也须匹配prod且为已发布配置。实例重启先恢复缓存，再同步拉取；Admin暂时失败继续使用最后成功配置。没有兼容发布/缓存时仅拒绝AI调用，不静默切换来源。部署预检失败不会替换现有容器。

本地与离线评测使用Admin导出的完整快照。评测入口在任何模型导入前选择snapshot模式并固定所有线程的配置，主/备/Judge/Tool使用同一包；结果记录快照id/digest及revision/sequence。评测的显式模型/variant实验不改源包。`tests/fixtures/`只供单测历史回归，镜像不包含。参数与运行命令唯一说明见[配置入口](../../duxue-server/agent_specs/README.md)。代码已支持正式接入；现网切换随本轮代码合入main及预备环境后完成，本地实施不直接替换正式服务。

Companion协调入口、Planning/Reflection工作流、Tutoring轮次、任务/计划提取、Sprint预览、自述维度提取均固定一次`ContextVar`快照；嵌套调用保留外层版本，不在中途切换。独立模型适配器也解析当前已发布目录。原计划/任务路径中启动时缓存的动态Prompt已改为从同一快照渲染；复用的导师备用网关也按当前快照重新解析模型，不缓存旧spec，避免发布模型参数却仍使用旧Prompt或旧备用模型。

发布记录不等于实例已加载，以回执为准。回滚重新验证兼容历史产物，只切换环境指针，不改历史；当前执行中的调用保留旧快照，新调用在实例加载后使用新快照。观测记录发布ID/digest及实际模型/Prompt身份；Admin模式内部定义版本等于包digest，不再以Git手工版本作为发布标识。

## 五、界面与真实调试

主入口为Workflow、Agent、发布管理，调试记录作为次要导航。根路径直接进入Workflow，不再提供工作概览、重复统计和通用步骤说明。所有内容区操作集中在右侧操作栏；Agent详情编辑按钮在页标题右上角，单Agent编辑不占用只有一个项目的文件侧栏。流程查看与表格导航保持只读。

发布管理集中展示当前发布、当前环境唯一一份待发布修改（影响组件/校验与调试覆盖，可直接进入完整差异）、不可变版本表格，以及当前版本的服务端同步回执。回执详情按需展开，不把所有旧实例当成在线实例。Agent详情负责编辑/保存/调试；最终发布只在发布管理执行。`/releases/<id>`可查看历史文件、下载完整产物及回滚，受原兼容性与generation约束。

没有working草稿时，下次编辑从当前发布创建；没有发布则由管理员从已有Admin备份快照显式导入。后续所有Agent共享同一个working配置包；放弃修改仅归档该行。后台审计记录继续保留，但删除操作审计页面与列表数据加载。

调试记录以表格显示调试对象名称/稳定ID、流程或组件类型、发布基线/配置快照摘要、输入摘要、结果和时间，详情显示实际输入、模型、Prompt、候选与Judge步骤。不能只凭提问文本辨认调试对象；未记录历史基线时明确标注未知。


Workflow菜单位于Agent上方：列表含Workflow、简介、配置。详情用React Flow+Dagre画真实Node/Edge，支持点击查看、平移/缩放及完整JSON。Agent/代码Agent、Judge/代码Gate、固定代码Action按登记类型显示；重试回路保留，不强行转为无环DAG；parent虚线仅表示归属。

Agent菜单统一展示25项组件，并按模型Agent、代码Agent、模型Judge、代码Gate、Tool筛选，搜索与类型同一行；表格显示修改状态，不显示组件v号或当前发布R号。`/agents/<id>`查看当前Admin发布配置，`?draft=<uuid>`编辑明确草稿。所有组件有编辑入口，字段按上表保护。没有独立“配置工作台”或“配置草稿”菜单；唯一待发布草稿与不可变版本统一放在“发布管理”。`/drafts/<uuid>`编辑同一完整包的依赖、对照、调试和发布，不复制另一份配置源。

调试通过内部鉴权API启动无shell的独立Python进程。正常Agent/Workflow详情的“调试已发布配置”读取不可变发布包；Agent草稿编辑页、`/workflows/<id>?draft=<id>`和完整草稿页使用已保存草稿。未保存修改必须先保存，不能在后台隐式使用编辑器中的临时值。每次执行固定完整配置包，图与调试面板也保持同一快照，不随随后发布切换。调试区域明确显示来源；这是调试溯源信息，不恢复普通组件页面的版本列。

调试交互统一采用右侧原生dialog抽屉：点击即打开并读取快照，输入框自动聚焦，抽屉独立滚动，Escape/关闭后返回原位置，移动端全屏。相同对象/快照关闭重开保留输入与结果，切换修订/目标时重置；Workflow运行后“查看流程执行”关闭面板并回到图。Agent草稿和完整包草稿在顶部提供入口，不把输入表单放在长页面底部。完整包的目标选择也在抽屉内。

尚未开放独立调试的对象，在详情入口处说明具体依赖（代码门禁的候选/权限/执行状态、动态Tool的调用上下文、固定正文Tool尚未开放单独入口、代码Agent的会话/检查点），不给会执行其他对象的调试按钮。根据实际登记的节点引用及工具消费者查找所属Workflow，提供跳转；能力限制是调试入口覆盖范围，不影响已实现的业务执行。

Agent详情的目标固定为当前组件，不提供跨Agent选择；有主备模型时仅选择当前Agent自己的模型。单模型调试复用组件调用和输入/输出双层契约；不自动执行其他Agent、Judge、工具或重试。模型输出中的工具请求仍属于原始候选；完整工具闭环由Workflow调试验证。服务端验证component_id属于目标Agent，代码组件未接入适配器则明确拒绝，不落入默认答疑流程。

当前已登记的Workflow独立调试：

| Workflow | 执行与输入 |
|---|---|
| Tutoring | 复用完整`TutoringWorkflow`；当前消息、可选受保护题、文字历史、任务标题、题目状态/尝试证据。覆盖上下文、导师、工具、Judge、重试、安全出口和题目推进 |
| Reflection | 复用`ReflectionWorkflow`；当前输入及可选review_date/review_feeling/review_reflection，既可检查等待分支也可执行确认分支 |
| task-intake | 复用`TaskIntakeService`与正式单Agent执行器；当前任务描述，授权孩子为独立测试fixture |
| review-aspects | 复用`propose_review_aspects`；孩子的原话总结 |
| sprint-intake | 复用`preview_spoken_sprint`；当前挑战描述 |

Tutoring/Reflection的读写在独立SQLite内存库中执行，测试身份和初始数据由隔离进程生成，不使用真实Ward/会话ID，不连接业务库读写；拟写入的消息/题目/学习事实可在结果查看，结束后回滚销毁，不投递Outbox。已有文字历史通过测试媒体适配器注入，当前不支持上传图片。代码Agent`tutoring.session-turn`、`reflection.session-turn`分别调用其自身的上述实现。Companion协调器、Planning检查点暂未接入独立隔离适配器，UI说明不可用；内部`tutoring-vet`/`tutoring-retry`随完整Tutoring执行并记录，不伪装成另一个独立业务入口。

调试上下文使用代码所有的受限Schema，不执行任意表达式。能力目录从Python返回，UI按实际能力展示入口。完整包草稿页可集中选择对象，但组件详情没有对象选择器。

执行证据使用ContextVar绑定的可选Recorder，普通业务运行不启用；通用执行器在实际节点执行和条件判断处采集，Tutor代码分支在实际发生处记录。事件包括workflow/node、父事件、输入/输出、状态、耗时、条件结果/所选边；重试分别记录，未经过节点不伪造数据。节点/边点击可查看本次记录，实际经过节点和已选边高亮，内部子流程事件保留在执行记录中。模型调用额外保留实际Prompt、提供商原始输出、校验后结果和Token；异常仍保留此前步骤，不能将安全兜底当作执行成功。

发布门禁仍只计入同revision/digest实际成功调用的component；Workflow运行不代表所有分支/备用模型已验证。执行代码摘要覆盖当前Python app源码，便于识别未提交修改产生的调试差异；提供商未返回的Token显示未知。单进程240秒、Next调用250秒，部署至少300秒请求。当前不提供取消、自动批量质量评测或跨版本一键对比，单次通过不代替教学质量评估。既有历史Trace继续在[Langfuse可观测性](../observability.md)中查看。

## 六、验证与运行

命令见[README](../../duxue-admin/README.md)。自动测试覆盖全部产物、编辑边界、非Tutoring热加载、动态Prompt、嵌套快照、Admin不可用拒绝默认值、损坏缓存保留、数据库约束、权限/并发及精确调试覆盖；真实联调覆盖非Tutoring模型调试、发布、加载回执与重启恢复。仅接收格式3；不提供历史格式转换或回滚兼容。


正式站点使用Next.js容器和仅在私有Docker网络可见的Python控制执行容器。后者复用现有Python代码，仅注册catalog/validate/debug与health，不启动业务API/Worker/配置拉取；APP_ENV=production时须显式AGENT_ADMIN_CONTROL_PROCESS=1并通过共享密钥鉴权。执行容器只有内存SQLite、无业务数据库/Redis/OSS凭据，模型密钥仅通过ECS私有环境提供。Node拥有管理数据库、账号认证与发布生命周期；目录POST接口接收Node从管理库读取的完整快照，执行器不保留默认Agent值。Node同时接入业务私有网络供Server读取发布，执行器仍只在Admin网络可见。

## 七、后续设计改进

当前调试属于真实执行冒烟，并不证明教学质量。下一步优先复用[离线评测](eval-offline.md)的小型固定回归集，评估答案保护、教学有效性与非答疑路由，再考虑设为发布门禁。导师备用模型与文本Judge默认同为qwen3.8-flash，独立调用仍存在相关误差；更换前应先验证候选模型的图片能力与质量，不仅按名称区别。

回滚发生在working草稿创建后时，现有发布基线检查会安全拒绝旧草稿发布；目前需要放弃并重新编辑。后续可提供结构化三方比较与无冲突变更重放。前端studio/API模块也可按编辑、调试、发布拆分，降低后续维护成本；这不需要引入流程编排。

## 本地环境配置

Admin本地唯一环境文件是`duxue-admin/.env`，显式提供`ADMIN_DATABASE_URL`、共享通信密钥及调试模型密钥；不读取旧`.env.local`或相邻Server环境。Node/CLI和本地Python隔离执行器共用此文件，启动步骤与参数见[README](../../duxue-admin/README.md#本机启动)。Python仅提供控制API，内存数据库且无配置拉取/业务启动；CI/Docker使用进程注入，不要求镜像含环境文件。正式ECS仍由私有`.env.prod`供Compose注入，本次本地配置简化不修改正式环境。
