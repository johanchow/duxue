# 读学 Server

当前 MVP 已打通注册、Ward、设备邀请与绑定、预签名上传、帧元数据、分析、日报与周趋势。

```bash
python -m uvicorn app.main:app --reload
python -m unittest tests.test_e2e -v
```

本地默认使用 SQLite 与本地文件存储；`/frames/upload-url` 仍遵守“先取预签名 URL、再 PUT、最后提交元数据”的生产契约。生产部署时由 OSS 适配器替换本地存储，移动端无需修改。
