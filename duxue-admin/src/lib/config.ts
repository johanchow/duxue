import path from 'node:path';
import dotenv from 'dotenv';
import { environmentSettings } from './environment';

export function config() {
  const root = process.env.ADMIN_ROOT || process.cwd();
  dotenv.config({
    path: path.join(root, '.env'),
    quiet: true,
  } as dotenv.DotenvConfigOptions);
  const environment = process.env.ADMIN_ENV || 'test';
  const raw = process.env.ADMIN_DATABASE_URL;
  if (!raw) throw new Error('请在duxue-admin/.env中配置ADMIN_DATABASE_URL');
  const settings = environmentSettings(
    environment,
    raw,
    process.env.ADMIN_PUBLIC_ORIGIN,
  );
  const token = process.env.AGENT_ADMIN_INTERNAL_TOKEN || '';
  if (token.length < 32) throw new Error('请配置至少32字符的内部通信密钥');
  return {
    ...settings,
    token,
    serverUrl: process.env.AGENT_SERVER_URL || 'http://127.0.0.1:8011',
  };
}
