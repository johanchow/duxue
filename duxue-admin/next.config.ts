import type { NextConfig } from 'next';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const config: NextConfig = {
  turbopack: { root: path.dirname(fileURLToPath(import.meta.url)) },
  output: 'standalone',
  outputFileTracingExcludes: { '/**': ['./.env*', './.local/**'] },
  devIndicators: false,
  poweredByHeader: false,
};
export default config;
