# 官网演示视频素材

实际录制安卓 App 的示例提问、在线 AI 回复、发音播放和冲刺操作。源码不包含账号、录屏或生成的视频；所有素材和构建结果位于被 Git 忽略的 `output/homepage-demo/`。

## 录制与来源

- Android SDK ADB、scrcpy、ffmpeg/ffprobe；录制机使用 macOS `say`/`afplay` 播放预设问题，手机麦克风进行真实 ASR。没有向 App 注入识别结果或模型回复。
- `record_take.py <name> --prompt '示例问题' --wait 20` 录制一次提问。ADB 可用环境变量 `ADB` 指定，默认取本机 Android SDK。
- `capture_controls.py <name> --seconds 40` 录制限时操作。操作坐标须按当时 UI dump 核实，不能照搬旧坐标。
- scrcpy 录制内部播放音频（AAC），保留 App 的真实读音。录制用 MKV 并等待 `--time-limit` 正常退出；强杀 MP4 可能没有 moov 索引，不能交付。
- 电脑播放的示例问题不在 Android 内部音轨中；成片语音输入章节按录制时间对齐同一份原始 AIFF，仅补回当时实际说出的原话，不替换为其他提问或冒充儿童声音。
- 图和回复均来自实际 App。剪去网络等待、重复操作及无关历史；片中注明示例题目、等待已剪短，局部放大只裁切实际画面。素材不上传第三方剪辑服务。

## 合成与校验

安装 Pillow 后执行 `python3 scripts/demo-video/build_video.py`，可用 `--font` 指定含中文的字体。本机默认 `/Library/Fonts/Arial Unicode.ttf`。渲染器使用 Pillow 制作章节与字幕图层，ffmpeg 保留实际屏幕视频；不需要 drawtext/ASS 滤镜。

`shots.json` 是唯一剪辑时间线；输出 `duxue-demo.mp4`、`duxue-demo-poster.jpg`、`duxue-demo.srt`、`duxue-demo.vtt`、`provenance.json` 与 `validation.json`。来源清单记录原始素材 SHA256、裁切区间和成片时间，便于核验。构建检查源片段边界、H.264/AAC、1920×1080、像素格式与时长；交付前须逐章抽帧、听发音并在浏览器检查实际解码。

用户验收视频后再接入官网，不把视频合成加入每次 APK 构建。官网部署约定以 `docs/deployment.md` 为准。
