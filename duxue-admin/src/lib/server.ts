import { config } from './config';
import { ApiError } from './auth';
export async function serverCall(path: string, body?: unknown) {
  const { serverUrl, token } = config();
  let response: Response;
  try {
    response = await fetch(serverUrl + '/internal/agent-admin/' + path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: {
        Authorization: 'Bearer ' + token,
        'Content-Type': 'application/json',
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: 'no-store',
      signal: AbortSignal.timeout(path === 'debug' ? 250000 : 30000),
    });
  } catch {
    throw new ApiError(503, '配置执行服务不可用，请检查连接或稍后重试');
  }
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof data.detail === 'string' ? data.detail : '配置请求校验失败',
    );
  return data;
}
