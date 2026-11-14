'use client';
import { useState } from 'react';
type Doc = Record<string, any>;
const time = (value: string) =>
  new Date(value).toLocaleString('zh-CN', { hour12: false });
export function LoadStatus({ state }: { state: Doc }) {
  const online = state.instances.filter(
    (item: Doc) => Date.now() - new Date(item.last_seen).getTime() < 90000,
  );
  const loaded = online.filter(
    (item: Doc) =>
      item.release_id === state.environment.release_id &&
      item.status === 'loaded',
  );
  return (
    <details
      className="load-status"
      open={online.some((item: Doc) => item.status === 'failed')}
    >
      <summary>
        服务端同步：{loaded.length}/{online.length} 个近期回执已加载当前版本
      </summary>
      {online.length ? (
        online.map((item: Doc) => (
          <div className="list-row" key={item.instance_id}>
            <code>{item.instance_id}</code>
            <span
              className={'badge ' + (item.status === 'failed' ? 'red' : '')}
            >
              {item.status === 'failed'
                ? '加载失败'
                : item.release_id === state.environment.release_id
                  ? '已加载当前发布'
                  : '等待同步'}
            </span>
            <small>{item.error || time(item.last_seen)}</small>
          </div>
        ))
      ) : (
        <p>尚无近期回执，请检查服务端配置连接。发布成功后仍需确认加载状态。</p>
      )}
    </details>
  );
}
export function VersionDetail({
  version,
  currentId,
  compatible,
}: {
  version: Doc;
  currentId: string;
  compatible: boolean;
}) {
  const files = Object.keys(version.bundle.files);
  const [file, setFile] = useState(files[0]);
  return (
    <section aria-label="版本详情">
      <div className="section-head">
        <div>
          <h2>
            配置内容{' '}
            <span className="badge">
              {version.id === currentId ? '当前发布' : '历史版本'}
            </span>
          </h2>
          <small>
            发布于 {time(version.created_at)} · {files.length} 份配置
          </small>
        </div>
      </div>
      {version.id === currentId && (
        <p role="status" className="notice">
          R{version.sequence}已发布。实例加载状态请在发布管理中查看。
        </p>
      )}
      {!compatible && <p className="notice">旧协议或不兼容，仅供查看历史。</p>}
      <label>
        配置文件
        <select value={file} onChange={(event) => setFile(event.target.value)}>
          {files.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      </label>
      <pre>{JSON.stringify(version.bundle.files[file], null, 2)}</pre>
      <details>
        <summary>完整发布产物与验证信息</summary>
        <pre>{JSON.stringify(version, null, 2)}</pre>
      </details>
    </section>
  );
}
