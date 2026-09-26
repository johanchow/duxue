# 重启服务后计划整理仍然不可用

08:19 重启的 `python main.py` 父进程仍是原来的 zsh，环境里继续带着 `http_proxy` / `https_proxy=http://127.0.0.1:7897`。计划整理用的 OpenAI 客户端会读取这个代理；7897 没有进程在听，所以仍是连接被拒绝，App 继续看到「计划整理暂不可用，请稍后重试。」

DashScope 的 HTTP 客户端改为 `trust_env=False`，不再继承 shell 代理。语音 WebSocket 此前已单独直连。
