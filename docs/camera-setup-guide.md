# 摄像设备接入与家庭实验手册

> 更新：2026-11-08。Go网关与云端接入已实现；TL-IPC43CL-V2 2.0在Mac系统终端完成真实RTSP→OSS→测试库五帧短测。机位确认、连续3小时及断网/断电等现场验收仍待完成。
> 配置、协议与验收事实源：[采集网关设计](technical/design-gateway.md)。

## 一、准备

- 标准持续供电摄像头，已启用本地 RTSP 或 JPEG 快照；确认具体型号/固件、接口路径、本地账号，断外网也能取图。
- 同局域网电脑；家庭首次在前台运行，电脑需保持唤醒。路由器关闭客户端隔离，建议按MAC保留摄像头IP。
- 网关编译程序与 FFmpeg。运行端无需 Python/Go 编译器；自行从源码构建时才需要 Go。无需 NVR、存储卡或云录像套餐。
- 已存在且经监护人授权的 Ward，以及更新到网关接口版本的读学服务端。真实 OSS 直传验收需要实际 OSS 后端；本地文件存储仅验证协议。

## 二、机位与本地取图

摄像头架在学生侧后方约45°，覆盖桌面、双手和书本，尽量规避正脸；此机位不是匿名化措施。固定支架，关闭音频、自动追踪和非必要云上传，让孩子知晓观察状态和停止方法。

使用已验机型的低分辨率子码流，约640×480起步。RTSP解码由FFmpeg承担；快照模式直接请求已验证的JPEG接口，目前支持HTTP Basic认证，不承诺所有厂商的Digest/ONVIF认证。接口地址、子码流和画面新鲜度须现场核实。

## 三、一次性配置云端访问凭证

由受信部署者在服务端开发/运维环境执行；将示例Ward UUID换成实际授权孩子的ID。脚本只生成文件，不连接数据库、不发起绑定，也不打印Token：

```bash
cd duxue-server
.venv/bin/python scripts/create_gateway_credentials.py \
  --gateway-id home-01 \
  --ward-id 00000000-0000-4000-8000-000000000001 \
  --output-dir /tmp/duxue-home-credentials
```

输出目录必须尚不存在，权限0700；其中两个文件权限0600：

| 文件 | 用途 |
|---|---|
| `server.env` | 将其中 `GATEWAY_CREDENTIALS_JSON` 配入服务端受限环境，重启API后生效；如果已有其他网关，合并JSON记录，不覆盖原配置 |
| `gateway.env` | 安全保存到网关运行电脑；包含 `DUXUE_GATEWAY_TOKEN`，不提交仓库 |

同一网关授权多个Ward时，重复传 `--ward-id`。一台摄像头固定关联一个Ward，不能直接改同一个camera_id的归属。换IP只改连接地址；摄像头账号与网关Token互不混用。

服务端需先应用迁移 `20261101_31` 再启动新接口。生产迁移和服务部署由操作员按既有发布流程执行，本手册不代表自动完成。

摄像头图片使用`OSS_BUCKET_CAMERA`。若它与附件桶不在同一区域，需要在服务端填写`OSS_CAMERA_ENDPOINT_PUBLIC`和`OSS_CAMERA_ENDPOINT_INTERNAL`；不填写则复用通用OSS endpoint。只填写摄像头公网endpoint时，生产读取也走该公网地址，避免误用另一区域的内网地址。公网签名上传始终使用HTTPS，裸域名或HTTP配置会归一为HTTPS，生产内网读取保留独立配置。可用OSS的桶信息接口核实真实区域；不能只根据通用endpoint推定摄像头桶区域。

## 四、构建、配置与运行

开发电脑从源码构建；已有对应平台发布包时直接使用包内程序，跳过构建：

```bash
cd duxue-gateway
mkdir -p dist
go build -trimpath -o dist/duxue-gateway ./cmd/duxue-gateway
cp configs/config.example.yaml config.yaml
chmod 600 config.yaml
```

编辑 `config.yaml`：填写服务端地址、本地camera_id、实际ward_id、已验证RTSP地址。API地址应包含部署所需前缀，例如线上 `https://<域名>/api/v1`；直接运行本仓库FastAPI时可使用 `http://127.0.0.1:8000`。云端HTTP只允许loopback开发地址。

状态目录相对于配置文件解析。例如根目录 `config.yaml` 中设置 `state_dir: ./state`；直接使用位于 `configs/` 的示例时，`./state` 位于 `configs/state`，同样不会入Git。Linux systemd部署使用 `/var/lib/duxue-gateway`。配置中的凭证字段引用环境变量名，不填真实密码。

将摄像头账号保存在受限环境文件中（例如把以下条目追加到私有 `gateway.env`，替换示例值）：

```dotenv
CAMERA_01_USERNAME='<摄像头本地账号>'
CAMERA_01_PASSWORD='<摄像头本地密码>'
```

在运行终端加载私有环境后校验和启动；将示例环境文件路径换成实际位置：

```bash
set -a
source /tmp/duxue-home-credentials/gateway.env
set +a
./dist/duxue-gateway config-check -config config.yaml
./dist/duxue-gateway run -config config.yaml
```

`config-check`校验配置与环境变量，不证明摄像头/服务端可达。RTSP需要FFmpeg在PATH中，或填写配置的 `ffmpeg_path`。首次运行必须联网完成自动登记；后续可以使用持久登记快照离线启动并缓存。

另一个终端可在进程运行期间只读查询本地状态；状态查询不要求加载秘密环境：

```bash
./dist/duxue-gateway status -config config.yaml
```

输出逐摄像头最后采图/提交时间、累计采图数、采样缺口、重连数、积压帧/字节、丢弃数和错误码。计数跨网关重启保留，验收时记录运行前后差值。状态来自本地数据库，不代表云端已分析，也不自动表示当前进程仍在线。

Ctrl+C或SIGTERM停止采集与上传并保留待传帧，下次运行恢复。首期没有独立暂停/排空命令；修改配置需停止后重启。不要同时运行两份共享同一状态目录的网关。

## 五、故障与恢复

| 情况 | 行为与处理 |
|---|---|
| 外网断、局域网正常 | 持续采图排队，恢复后补传；保持原采图时间、身份与key |
| 摄像头断电/局域网断 | 自动重连并记录缺口；没有采到的帧不能事后补回 |
| API偶发401 | status显示gateway_auth=retrying，暂停上传并退避心跳探测；探测成功自动恢复原帧上传，无需重启 |
| 网关凭证持续无效 | 连续3次探测401后status显示gateway_auth=required，关闭采集并退出78；修复凭证后重启，systemd不会对此自动重启 |
| 摄像头授权撤销（403） | 关闭对应FFmpeg并停止该源上传；其他摄像头继续。待传帧保留至TTL，只有明确的数据清除错误才立即删除 |
| Ward已删除或历史数据已清除 | 停止对应源并清理对应待传帧；清除历史数据保留停用标记，旧camera_id不会自动恢复。重新启用需操作员显式配置新编号；其他403不能被推断为已清除 |
| 缓存超限/超过TTL | 可控淘汰并计数；保护正在上传的帧；磁盘不足停止新帧落盘 |
| 上传成功但确认响应丢失 | 重试同frame_id/key，云端返回原Frame，不重复生成事实 |
| 网关被强制结束 | 重启恢复文件/SQLite；验证JPEG摘要；已交付帧不复活 |
| 单个孤儿manifest损坏 | 删除该损坏目录并记录缺口，其他帧继续恢复；无法识别归属时status列出网关级unattributed_recovery_losses，各摄像头行显示同一计数 |

离线但网关运行时仍执行TTL；关机期间无法物理清理，启动时先恢复/清理再上传。心跳正常只证明网关到云端可达，不能掩盖摄像头故障。status/log包含有界、脱敏的capture_error_detail，可区分FFmpeg认证失败、超时和编码报错；原始诊断不上传心跳。RTSP凭证通过私有管道传给FFmpeg，不放入进程参数或临时文件。首次run自动将本地SQLite队列schema 1升级到2并保留待传帧，之后不要换回旧二进制。清除数据时已发出的短期OSS上传授权不能即时撤销，晚到对象由现有Celery孤儿清理任务删除；部署时需同时更新并运行API、worker和beat。

## 六、发布包与Linux常驻运行

开发环境执行以下命令生成macOS arm64、Linux amd64/arm64包和校验和；不上传、不发布：

```bash
cd duxue-gateway
./scripts/build.sh
```

产物位于 `dist/`，每个包包含程序、配置与systemd模板。FFmpeg默认单独安装，不随包分发；跨平台编译通过不等于该平台已完成运行实测。

Linux按 `deploy/duxue-gateway.service` 部署：准备 `duxue-gateway` 服务账号，将程序放到 `/opt/duxue-gateway/duxue-gateway`、配置放到 `/etc/duxue-gateway/config.yaml`、私有环境放到 `/etc/duxue-gateway/credentials.env`（0600）。模板通过StateDirectory创建持久目录，运行账号需能执行FFmpeg并访问局域网。安装服务文件后由操作员启用服务，使用systemctl/journalctl查看状态；不要把Token放到ExecStart参数。

## 七、家庭现场验收

按 [技术验收清单](technical/design-gateway.md#五最小实验与验收) 记录连续3小时成功率、真实OSS对象/Frame一致性、断外网10分钟补传、摄像头断电重连、强杀恢复及两摄像头隔离。

自动化合成画面测试不代替真实RTSP和OSS验收；采集成功也不等于动笔/思考/卡壳识别准确或晚间报告已完整落地。

### 单独验证真实RTSP解码

源码环境提供显式启用的实机测试，复用网关生产取图路径，验证三张可解码、时间递增的新鲜JPEG及640像素输出宽度；不保存图片、不上传云端。未设置地址时，普通测试自动跳过该项。

在已加载摄像头私有环境变量的终端中执行：

```bash
cd duxue-gateway
export GATEWAY_LIVE_RTSP_URL='rtsp://<摄像头IP>:554/stream2'
export GATEWAY_LIVE_CAMERA_USER="$CAMERA_01_USERNAME"
export GATEWAY_LIVE_CAMERA_PASSWORD="$CAMERA_01_PASSWORD"
go test ./internal/infrastructure -run '^TestLiveRTSPFreshJPEG$' -count=1 -v
unset GATEWAY_LIVE_CAMERA_PASSWORD GATEWAY_LIVE_CAMERA_USER GATEWAY_LIVE_RTSP_URL
```

TP-LINK TL-IPC43CL-V2 2.0的子码流实际提供H.264；已在Mac系统终端完成认证、解码、采图及真实OSS接收五帧短测。该结果不代表长期稳定性或行为分析准确度已验收。该系列设备密码/视频加密密码用于本地访问，不要混用物联App登录密码，账号和路径以实机为准。

macOS若出现同机Python能连接摄像头、FFmpeg立即报`No route to host`，先检查“系统设置 → 隐私与安全性 → 本地网络”中运行网关的宿主应用权限。本次现场用户确认Codex开关已开启，Codex启动仍失败，但系统终端运行同一网关脚本成功；差异位于运行环境，具体权限或网络策略原因尚未证实。不要直接归因于摄像头掉线，也不要通过转发绕过权限。Apple的[本地网络隐私说明](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)解释了宿主应用与子进程的权限归属。
