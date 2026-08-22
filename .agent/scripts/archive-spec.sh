#!/usr/bin/env bash
# 归档已完成 spec：校验 status:done 后，把 .agent/specs/<slug>.md 移入 .agent/specs/done/ 并更新索引。
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

SPECS="$ROOT/.agent/specs"
DONE="$SPECS/done"
src="$SPECS/$slug.md"

if [[ ! -f "$src" ]]; then
  echo "❌ 未找到 $src" >&2
  exit 1
fi

# 校验：spec 必须已标 status: done（收工前置）
if ! grep -q '^status: done' "$src"; then
  echo "❌ $src 未标记 status: done（先在顶部 front-matter 置 done 再归档）" >&2
  exit 1
fi

mkdir -p "$DONE"
mv "$src" "$DONE/$slug.md"

# 更新索引（简单表格，无 memory 索引依赖）
INDEX="$DONE/README.md"
if [[ ! -f "$INDEX" ]]; then
  printf '# 已归档 spec\n\n| spec | 归档日 |\n|------|--------|\n' > "$INDEX"
fi
date="$(date +%Y-%m-%d)"
if ! grep -q "| $slug.md |" "$INDEX"; then
  printf '| [%s.md](%s.md) | %s |\n' "$slug" "$slug" "$date" >> "$INDEX"
fi

echo "✅ 已归档 .agent/specs/done/$slug.md"
echo "下一步: git add -A && git commit（done + 归档 + 索引，与代码同一 commit）"
