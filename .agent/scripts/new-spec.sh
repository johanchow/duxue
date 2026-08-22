#!/usr/bin/env bash
# 新建单文件 spec 脚手架：
#   建 .agent/specs/<slug>.md（front-matter + 模板），slug 由调用者（通常 agent）起名。
# 用法：bash .agent/scripts/new-spec.sh <slug>   （如 add-login-page）
set -euo pipefail

slug="${1:-}"
if [[ -z "$slug" ]]; then
  echo "用法: bash .agent/scripts/new-spec.sh <slug>   (短横线小写英文，全局唯一，如 add-login-page)" >&2
  exit 1
fi

# 脚本在 .agent/scripts/ 下，上溯两级到仓库根
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
specs="$root/.agent/specs"
mkdir -p "$specs"

dir="$specs/$slug.md"
if [[ -e "$dir" ]]; then
  echo "已存在: $dir（slug 撞号，请换名）" >&2
  exit 1
fi

author="$(git -C "$root" config user.name 2>/dev/null || echo "unknown")"
created="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cat > "$dir" <<EOF
---
slug: $slug
created: $created
status: draft
---

# $slug spec

## 做什么 / 为什么
<!-- 一句话讲清目标与动机 -->

## 验收标准
- [ ] 
- [ ] 

## 实现计划（Gate 1：填完等人确认，不许自转）
- 影响文件：
- 测试计划：

## 实现清单（完成度，做完一项把 [ ] 改成 [x]）
- [ ] 搭脚手架
- [ ] 
- [ ] 

## 备注
EOF

echo "已创建 $dir"
echo "  front-matter: slug=$slug created=$created author=$author"
echo ""
echo "下一步: 填『验收标准』+『实现计划』 → 等确认(Gate1) → 小步实现每步配测 → 勾 [x] → 验收(Gate2) → bash .agent/scripts/archive-spec.sh $slug"
