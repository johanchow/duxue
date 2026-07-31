# 读学 Admin

第一期运营台只提供租户内 Ward、设备在线状态、待分析帧与报告数量概览，不提前实现文档中尚未开放的 IP/萤石摄像头接入。

```bash
python3 -m http.server 4173 --directory duxue-admin
```

页面默认连接 `http://localhost:8000`，仅接受 owner/admin 角色访问汇总接口。
