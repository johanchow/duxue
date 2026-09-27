# 按住说话：识别不可用与「正在听」浮层不消失

本机 shell 设置了 `http_proxy` / `https_proxy` 指向 `127.0.0.1:7897`，但该端口没有进程在听。服务端把这段音频转给 DashScope 时，`websockets` 会沿用这个代理，连接被拒绝，接口就回 `voice transcription is temporarily unavailable`。不走代理时，同一条 DashScope 地址可以连上。

客户端在 `start()` 还没返回时就收到这个错误。错误处理先把录音状态清掉，随后启动流程又把「松开发送 / 正在听」浮层插上去，松手后的结束回调不会再来，浮层就留在屏幕上。识别一旦在浮层出现前失败，就不再插入浮层。
