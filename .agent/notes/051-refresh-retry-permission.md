# 刷新成功不等于资源获授权

> 日期：2026-09-13

## 现象

Ward 端请求仅 guardian 可访问的 `/wards/{ward_id}/devices` 时，服务端返回 401。客户端成功调用 `/ward-auth/refresh` 后，用新 token 重试仍为 401，却错误清空了本地会话，随后任何 Ward 请求都会变成无 token 的 401。

## 根因与规避

`ApiClient._handleError` 将「refresh 请求失败」和「refresh 成功、原始资源重试失败」放在同一个 `catch` 中。后者代表角色/资源权限拒绝，不能推断 refresh token 无效。

刷新只在 `_refreshOnce()` 本身失败时调用 `_expireSession()`；成功刷新后的重试错误直接向调用方返回并保留新凭证。`test/api_client_test.dart` 覆盖该情形，防止未来将所有 401 再次一概视为登出条件。
