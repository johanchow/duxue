# 摄像设备接入与家庭实验手册

> 更新：2026-11-01。Go 网关与云端接入已实现；自动化测试使用合成画面、本地存储和临时数据库。真实摄像头、OSS与连续3小时验收仍待完成。
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
| 凭证无效/授权撤销 | 上传暂停并记录错误，修复服务端授权/本机凭证后重启；永久冲突帧不快速重试 |
| Ward已删除或历史数据已清除 | 停止对应源并清理对应待传帧；清除历史数据保留停用标记，旧camera_id不会自动恢复。重新启用需操作员显式配置新编号；其他403不能被推断为已清除 |
| 缓存超限/超过TTL | 可控淘汰并计数；保护正在上传的帧；磁盘不足停止新帧落盘 |
| 上传成功但确认响应丢失 | 重试同frame_id/key，云端返回原Frame，不重复生成事实 |
| 网关被强制结束 | 重启恢复文件/SQLite；验证JPEG摘要；已交付帧不复活 |

离线但网关运行时仍执行TTL；关机期间无法物理清理，启动时先恢复/清理再上传。心跳正常只证明网关到云端可达，不能掩盖摄像头故障。日志只包含稳定编号和错误类别，不包含图片或凭证。清除数据时已发出的短期OSS上传授权不能即时撤销，晚到对象由现有Celery孤儿清理任务删除；部署时需同时更新并运行API、worker和beat。

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
