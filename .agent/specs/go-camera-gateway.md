---
slug: go-camera-gateway
created: 2026-11-01T02:21:58Z
status: draft
---

# Go 摄像头采集网关与云端接入 spec

## 做什么 / 为什么

用户已确认 Go + FFmpeg + SQLite，在同一仓库新建独立 duxue-gateway 项目。完成家庭固定工位的无绑定码采集链路：本地 camera_id/RTSP账号/ward_id配置，统一受限网关认证，稀疏采图、持久缓存、OSS直传与Frame登记。架构与协议唯一事实源：[采集网关设计](../../docs/technical/design-gateway.md)。

Gate 1 已由用户于2026-11-01确认。实现与自动化验收已完成，正在保留真实设备/OSS现场验收与Gate 2；未将现场项目标成完成。

## 范围

- Go本地网关、必要的Python云端接入扩展、数据库迁移、CI构建测试和部署手册。
- 保留旧逐设备接入接口；云端不改为Go，不修改答疑、计划或Memory模型。
- 无本地Web后台、绑定码、逐摄像头云端Token、换座热更新、自动发现、远程实时视频或新增分析事件。
- 不自动部署生产、不运行生产迁移、不发布远程版本。真实摄像头/OSS现场验证单列，不能用模拟测试冒充通过。

## 验收标准

### 自动化代码验收

- [x] Go module独立构建，固定工具链/依赖；可在CGO_ENABLED=0下为macOS arm64和Linux amd64/arm64构建。
- [x] CLI支持配置校验、前台运行、本地状态查询与正常退出；本地凭证仅引用环境变量；配置错误可定位且不泄密。
- [x] 每15s通过FFmpeg从RTSP取新鲜JPEG；支持HTTP快照适配；不采音频，不保存完整视频；模拟单路失败不阻塞其他摄像头。
- [x] SQLite与文件队列在重启后恢复；归属、frame_id、采集时间和摘要不可改；崩溃窗口与过期/丢失/终态文件均有测试。
- [x] 统一网关凭证和Ward白名单生效；注册同摄像头同Ward幂等，不同Ward冲突；旧接口认证/行为回归通过。
- [x] 新上传预约/续签复用key；OSS PUT结果未知、Frame响应丢失均只产生一个Frame及一份既有采集事实；跨网关/key/归属/摘要冲突全部拒绝。
- [x] 容量/TTL/磁盘保护、退避、永久错误阻塞、公平补传、取消与FFmpeg子进程回收通过故障测试。
- [x] 网关/逐摄像头健康分开记录；心跳不掩盖取图失败；并发/重启后的心跳顺序不覆盖新快照。
- [x] 云端PostgreSQL迁移、唯一约束、并发幂等与Frame+Outbox原子性测试通过；不以SQLite代替。
- [x] Go单元/集成与竞态检查、相关Python测试/旧接口回归、构建检查全绿；源码和日志无真实凭证。
- [x] 实际CLI、配置、部署和依赖说明写入操作手册；架构中已实现/待验证状态准确。

### 家庭现场验收（需要实际设备与受权测试环境）

- [ ] 真实RTSP与OSS完整链路跑通，图像取景/新鲜度/时间/设备/Ward归属正确，无需Plan/StudySession。
- [ ] 连续3h约720采样点，完整链路成功率目标≥98%，明确计入失败与缺口。
- [ ] 断外网10min继续缓存，恢复后按原时间/归属补传；摄像头断电自动重连；强制结束进程可恢复。
- [ ] 两摄像头故障与归属隔离实测；未完成时明确标记待验，不声称网关已具备多路容量保证。

## 实现计划（Gate 1：填完等人确认，不许自转）

### 1. 项目、环境与配置

影响：新建 duxue-gateway/go.mod、go.sum、cmd/duxue-gateway、internal分层、configs/config.example.yaml、构建脚本和忽略规则。

- 使用当前可用Go 1.27.1作为起始工具链并在项目固定；先核实依赖最低Go版本和三平台支持。
- 核实并锁定无CGO SQLite驱动和YAML库；其余功能优先标准库，不引入Web框架。
- 以config-check/run/status等CLI子命令明确入口，具体参数以实现后手册为准。
- 测试：合法/缺失/重复camera_id、未知配置项、凭证脱敏、单实例锁、正常退出。

### 2. 领域与持久队列

影响：duxue-gateway/internal/domain、application、infrastructure中的SQLite/文件适配及迁移。

- 先写FrameDelivery状态机与不可变归属测试，再实现；保存帧证据、预约、重试和租约。
- JPEG/manifest先落盘、SQLite事务后确认；实现RecoverLocalState、限额/TTL、清理与崩溃恢复。
- 测试：逐个崩溃边界、幂等恢复、数据库锁/磁盘失败、上传与清理互斥、已过期图片不重传。

### 3. 服务端网关API与迁移

影响：duxue-server/app/contexts下设备采集领域与Application实现；app/api/v1/gateway_ingestion.py和相关DTO/router；app/bootstrap/settings.py；infrastructure/persistence/models.py及新增Alembic迁移；storage/auth适配；相关测试。

- 云端扩展现有Device/Frame，新建上传预约/健康技术状态；新增字段可空兼容历史数据。
- 实现预配置凭证哈希、稳定gateway_id、Ward白名单；按架构提供登记、上传预约、提交、心跳四个接口。
- 校验授权/登记/时间/对象大小与摘要；同一Frame事务写既有LearningFact Outbox，不新增分析编排。
- 现有Ward删除与设备撤销路径须适配新登记，不能只撤销旧Device Token而仍允许网关上传。
- 测试：API契约、跨域越权、并发注册/提交、重试、授权撤销、Ward删除、对象校验、旧设备接口回归。
- PostgreSQL执行迁移/唯一约束集成测试；新增独立测试配置，不以开发者.env中的库做破坏性测试。

### 4. 取图、上传与运行管理

影响：duxue-gateway/internal/infrastructure的FFmpeg/HTTP/调度适配，Application Commands/Queries和bootstrap。

- 每摄像头独立采样；FFmpeg持续解码取新帧，控制背压与缓冲；凭证仅用于对应摄像头。
- API/OSS使用分离客户端；有界上传、同key续签、指数退避及公平补传；进程信号停止采图并安全退出。
- 测试：FFmpeg生成测试源的解码冒烟；模拟相机/API/OSS超时、失效URL、丢响应、鉴权与429；Go进程重启恢复端到端测试。

### 5. 构建、交付与文档

影响：duxue-gateway/deploy、scripts、.github/workflows/gateway-ci.yml；docs/technical/design-gateway.md、design-server.md、docs/camera-setup-guide.md、deployment.md、observability.md及AGENTS.md/.agent/notes状态导航。

- 提供本机运行与Linux systemd模板、可重复的三平台构建包；明确FFmpeg为外部依赖，不宣称单文件包含全部运行环境。
- CI运行Go测试/静态检查和交叉编译；相关服务端测试归现有Server CI。
- 现场验收依赖实际摄像头地址/账号、指定Ward和受权测试OSS；后续接入时再由操作员配置，不写进仓库。

### 测试执行计划

- Go：go test ./...、go vet ./...；宿主支持CGO时独立执行go test -race ./...，不能将其与CGO_ENABLED=0的交叉构建混淆。
- Go发布：CGO_ENABLED=0按目标GOOS/GOARCH构建；编译通过与目标平台运行实测分别记录。
- Python：使用duxue-server/.venv及requirements约定运行相关pytest，再跑必要回归；导入前OTEL_SDK_DISABLED=true，mock外网模型。
- PostgreSQL：受控临时实例或Testcontainers，执行迁移/并发/事务测试；真实OSS现场用例另记录。
- 文档：链接/锚点、实际命令与状态一致性、git diff --check和提交前review。

## 实现清单（完成度）

- [x] 核对当前代码、工具链与目标接入差异，记录Go技术选型。
- [x] 填写范围、验收和实施/测试计划。
- [x] Gate 1：用户确认本文件细化计划。
- [x] 初始化独立Go项目、配置和CLI。
- [x] 领域模型、SQLite/文件队列与恢复测试通过。
- [x] Python云端新API、兼容迁移与PostgreSQL测试通过。
- [x] FFmpeg取图、上传调度、心跳和端到端故障测试通过。
- [x] CI构建、部署材料和实际运行文档同步。
- [ ] 真实摄像头/OSS与家庭故障场景验收。
- [ ] Gate 2：用户验收；沉淀最终决策并归档spec。

## 备注

- 当前开发机已检测到Go 1.27.1、FFmpeg和Docker命令；尚未验证Docker服务运行或目标平台运行结果。
- 当前架构文档已定义业务协议；细化计划确认不代替真实运行验收。


## 自动化验证记录（2026-11-01）

- 服务端完整回归：741 passed，包含临时真实PostgreSQL、新迁移升降级、并发幂等、Outbox原子性、数据清除与凭证生成工具；外网模型均mock。
- Go：go test -race ./...、go vet ./...通过，包含新增RTSP协议与发布包隐私边界测试。覆盖SQLite/文件崩溃窗口、过期URL续签、两路隔离/公平、清除数据时的在途采集和启动孤儿恢复。
- 实际RTSP路径：本地合成H.264通过RTSP/RTP over TCP握手并由生产SourceFactory提取新鲜JPEG；使用FFmpeg原生timeout参数。
- 实际Go二进制→独立FastAPI进程→本地不可覆盖对象存储→Frame/Outbox联调、强杀重启与无秘密环境的status查询通过。
- CGO_ENABLED=0三平台编译与打包通过；产物位于duxue-gateway/dist并忽略Git，尚未运行远程CI或在Linux硬件上实测。
- Docker daemon不可用，因此PostgreSQL测试采用本机临时独立cluster；完整回归显式使用临时数据库，未执行开发/生产Alembic迁移。
- 真实摄像头地址/凭证及受权测试OSS尚未配置，家庭长测按独立现场清单待执行；spec不归档为done。

### 复核修复验证

- 预约接收后同事务删除，旧预约分页清理；损坏孤儿manifest隔离与缺口幂等；403关闭源；私有管道RTSP凭证与有界脱敏诊断；401自动探测恢复/持续失败退出，均先红后绿。
- 服务端全量742 passed（包含1007条预约分页、PostgreSQL并发接收及Outbox回滚后保留预约、实际Go二进制联调），既有FastAPI弃用警告1条；Go全量竞态检查、go vet及三平台重建通过。
- 家庭现场验收状态不变；未部署到开发/生产。
