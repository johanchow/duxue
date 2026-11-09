'use client';
import { useEffect, useRef, type ReactNode } from 'react';
export function DebugDrawer({
  open,
  onClose,
  loading = false,
  error,
  children,
}: {
  open: boolean;
  onClose: () => void;
  loading?: boolean;
  error?: string;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = ref.current;
    if (!open || !dialog) return;
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    dialog.showModal();
    document.body.style.overflow = 'hidden';
    return () => {
      dialog.close();
      document.body.style.overflow = overflow;
      previous?.focus();
    };
  }, [open]);
  useEffect(() => {
    if (open && !loading)
      ref.current
        ?.querySelector<HTMLTextAreaElement>('textarea[aria-label="调试输入"]')
        ?.focus();
  }, [open, loading]);
  return (
    <dialog
      ref={ref}
      className="debug-drawer"
      aria-label="调试面板"
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          const rect = event.currentTarget.getBoundingClientRect();
          if (
            event.clientX < rect.left ||
            event.clientX > rect.right ||
            event.clientY < rect.top ||
            event.clientY > rect.bottom
          )
            onClose();
        }
      }}
    >
      <div className="debug-drawer-heading">
        <h2>调试</h2>
        <button className="secondary" onClick={onClose} aria-label="关闭调试">
          关闭
        </button>
      </div>
      <div className="debug-drawer-content">
        {loading ? (
          <p role="status">正在读取配置快照…</p>
        ) : error ? (
          <p role="status" className="notice error">
            {error}
          </p>
        ) : (
          children
        )}
      </div>
    </dialog>
  );
}
