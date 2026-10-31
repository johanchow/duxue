#!/usr/bin/env bash
# 收工：校验 status:done 后删除 .agent/specs/<slug>.md。
# 决策应已写入 .agent/notes/ 对应领域文件。历史留在 git，不保留 done/ 全文。
# 用法：bash .agent/scripts/archive-spec.sh <slug>
set -euo pipefail

slug="${1:-}"
if [[ -z "$slug" ]]; then
  echo "用法: archive-spec.sh <slug>" >&2
  exit 2
fi

ROOT="${CW_REPO_ROOT:-$(git rev-parse --show-toplevel 2>/dev/null || echo "")}"
if [[ -z "$ROOT" ]]; then
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fi

src="$ROOT/.agent/specs/$slug.md"

if [[ ! -f "$src" ]]; then
  echo "❌ 未找到 $src" >&2
  exit 1
fi

if ! grep -q '^status: done' "$src"; then
  echo "❌ $src 未标记 status: done（先在顶部 front-matter 置 done，并把决策写入 .agent/notes/）" >&2
  exit 1
fi

rm "$src"
rmdir "$ROOT/.agent/specs/done" 2>/dev/null || true

echo "✅ 已删除 .agent/specs/$slug.md"
echo "确认决策已写入 .agent/notes/ 对应领域文件，再与代码同一 commit。"
