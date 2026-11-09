import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = {
  title: '读学 · Agent Studio',
  description: 'Agent配置管理与发布',
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
