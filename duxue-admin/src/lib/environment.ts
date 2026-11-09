export function environmentSettings(
  environment: string,
  raw: string,
  publicOrigin?: string,
) {
  if (!['test', 'prod'].includes(environment))
    throw new Error('ADMIN_ENV只允许test或prod');
  const databaseName = `duxue-admin-${environment}`;
  const database = new URL(raw.replace(/^postgresql\+\w+:/, 'postgresql:'));
  if (!['postgresql:', 'postgres:'].includes(database.protocol))
    throw new Error('管理台需要PostgreSQL');
  database.pathname = '/' + databaseName;
  if (environment === 'prod') {
    if (
      !publicOrigin ||
      !publicOrigin.startsWith('https://') ||
      new URL(publicOrigin).origin !== publicOrigin
    )
      throw new Error(
        '正式环境需要HTTPS ADMIN_PUBLIC_ORIGIN（不含路径或末尾斜杠）',
      );
  }
  return {
    environment: environment as 'test' | 'prod',
    databaseName,
    databaseUrl: database.toString(),
  };
}
