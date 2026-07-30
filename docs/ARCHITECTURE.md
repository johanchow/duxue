# 读学系统 — 全系统架构概览

> 版本 v1.0 | 本文档描述整体系统结构与领域划分，各端详细设计见各子目录文档。

---

## 一、四端组成

| 端 | 目录 | 角色 | 说明 |
|----|------|------|------|
| 读学Eye（Cam App） | `duxue-cam/` | Android 摄像端 | 架设在 ward 桌面，负责 RTMP 推流 |
| 读学App | `duxue-app/` | Guardian 端 | 查看行为报告、管理分析配置 |
| Admin Web | `duxue-admin/` | 运营后台 | 机构与租户管理、系统运维 |
| Server | `duxue-server/` | 服务端 | REST API、AI 推理、数据存储 |

---

## 二、整体系统架构

```mermaid
graph TB
    subgraph 客户端
        CAM[📱 读学Eye<br/>Android 摄像端]
        APP[📱 读学App<br/>Guardian 端]
        ADMIN[🖥️ Admin Web<br/>运营后台]
    end

    subgraph 服务端
        subgraph 接入层
            NGINX[Nginx 反向代理]
            SRS[SRS 流媒体服务器<br/>RTMP 推流接收]
        end

        subgraph API服务
            API[FastAPI<br/>REST + WebSocket]
        end

        subgraph 任务层
            WORKER[Celery Worker<br/>AI 推理任务]
            BEAT[Celery Beat<br/>定时截帧 + 报告生成]
        end

        subgraph 存储层
            PG[(PostgreSQL<br/>业务数据)]
            REDIS[(Redis<br/>任务队列 + 缓存)]
            FS[📁 文件存储<br/>帧图片 / 模型文件]
        end

        subgraph AI推理
            VLM[Qwen3-VL<br/>结构化解析器]
            CLS[分类层<br/>prototypes.yaml]
        end
    end

    CAM -- RTMP推流 --> SRS
    CAM -- REST API --> NGINX
    APP -- REST/WS --> NGINX
    ADMIN -- REST --> NGINX
    NGINX --> API
    SRS -- Webhook --> API
    API --> PG
    API --> REDIS
    BEAT --> SRS
    BEAT --> REDIS
    WORKER --> VLM
    WORKER --> CLS
    WORKER --> PG
    WORKER --> FS
    REDIS --> WORKER
```

---

## 三、领域划分（限界上下文）

```mermaid
graph LR
    subgraph IAM["🔐 身份与访问 (Identity & Access)"]
        U[User 聚合根]
        T[Tenant 租户]
    end

    subgraph DEV["📷 设备管理 (Device)"]
        D[Device 聚合根]
        SK[StreamKey 值对象]
    end

    subgraph WARD["👦 被监护者 (Ward)"]
        W[UserWard 聚合根]
        AP[AnalysisProfile 聚合根]
        BL[BehaviorLabelConfig 实体]
    end

    subgraph CAP["🎞️ 帧采集 (Capture)"]
        F[Frame 聚合根]
    end

    subgraph ANA["🧠 行为分析 (Analysis)"]
        AT[AnalysisTask 聚合根]
        BS[BehaviorSegment 实体]
    end

    subgraph REP["📊 统计报告 (Report)"]
        R[Report 聚合根]
    end

    T --> U
    U --> W
    W --> D
    W --> AP
    AP --> BL
    D --> F
    F --> AT
    AT --> BS
    BS --> R
```

---

## 四、核心角色说明

| 角色 | 英文标识 | 说明 |
|------|---------|------|
| 监护人 | `guardian` | 家长、老师或机构管理员，拥有账号，负责配置和查看报告 |
| 被监护者 | `ward` | 孩子、学员等被观察对象，无账号，由 guardian 创建和管理 |
| 摄像设备 | `device` | 绑定到 ward 的摄像端，持有 `stream_key`，不走人类账号体系 |
| 租户 | `tenant` | 一个机构或家庭，所有数据在租户内隔离 |

> 系统设计不假设使用场景仅限于学习/教育，guardian 与 ward 关系可覆盖任意监护观察场景。

---

## 五、各端详细文档

- Server 架构与数据库设计：[duxue-server/docs/ARCHITECTURE.md](../duxue-server/docs/ARCHITECTURE.md)
- 产品需求与摄像端用户手册：[docs/product-requirements.md](./product-requirements.md)
