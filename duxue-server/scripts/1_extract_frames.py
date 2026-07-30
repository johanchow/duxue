"""
第一步：图片索引生成
扫描已有图片文件夹，生成后续步骤所需的 frames_info.json。

图片可来自任意来源（不同视频截图、手机拍摄、标注平台导出等），无需时间信息。

用法：
  python scripts/1_extract_frames.py --folder data/frames
"""

import json
import os
import sys
import argparse
from pathlib import Path
from PIL import Image


# 分辨率建议范围
MIN_SIDE = 320    # 短边最小值（低于此值细节不足）
MAX_SIDE = 1280   # 长边最大值（高于此值 token 消耗过多）


def check_image(img_path: Path) -> tuple[bool, str]:
    """
    检查单张图片是否符合建议规格。
    返回 (ok, warning_msg)，ok=True 表示无警告。
    """
    try:
        with Image.open(img_path) as img:
            w, h = img.size
    except Exception as e:
        return False, f"无法读取图片（{e}）"

    short_side = min(w, h)
    long_side  = max(w, h)
    ratio      = long_side / short_side

    warnings = []
    if short_side < MIN_SIDE:
        warnings.append(f"分辨率过低（{w}×{h}，短边 {short_side}px < {MIN_SIDE}px），细节可能不足")
    if long_side > MAX_SIDE:
        warnings.append(f"分辨率过高（{w}×{h}，长边 {long_side}px > {MAX_SIDE}px），建议缩图以节省 token")
    if ratio > 4:
        warnings.append(f"宽高比极端（{w}×{h}，{ratio:.1f}:1），可能影响 VLM 理解")

    return len(warnings) == 0, "；".join(warnings)


def build_index_from_folder(folder: str) -> list[dict]:
    """
    扫描图片文件夹，按文件名排序，生成 frames_info 列表。
    timestamp 填序号（0, 1, 2...），仅供内部排序，不代表实际时间。
    """
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    image_files = sorted([
        p for p in Path(folder).iterdir()
        if p.suffix.lower() in exts
    ])

    if not image_files:
        print(f"[错误] 文件夹内未找到图片（支持 jpg/png/webp）：{folder}")
        sys.exit(1)

    print(f"扫描到 {len(image_files)} 张图片，正在检查规格...\n")

    warn_count = 0
    frames_info = []
    for idx, img_path in enumerate(image_files):
        ok, msg = check_image(img_path)
        if not ok:
            print(f"  ⚠️  #{idx+1:04d} {img_path.name}：{msg}")
            warn_count += 1
        frames_info.append({
            "timestamp":   idx,
            "time_str":    f"#{idx+1:04d}",
            "filepath":    str(img_path),
            "description": ""
        })

    if warn_count:
        print(f"\n共 {warn_count} 张图片有警告，建议处理后再标注（不影响继续使用）")
    else:
        print("所有图片规格检查通过")

    print(f"\n✅ 索引生成完成，共 {len(frames_info)} 条")
    return frames_info


def main():
    parser = argparse.ArgumentParser(description="图片索引生成工具")
    parser.add_argument("--folder", required=True,                     help="图片文件夹路径")
    parser.add_argument("--info",   default="data/frames_info.json",  help="索引文件输出路径（默认 data/frames_info.json）")
    args = parser.parse_args()

    if not os.path.isdir(args.folder):
        print(f"[错误] 文件夹不存在：{args.folder}")
        sys.exit(1)

    if os.path.exists(args.info):
        answer = input(f"[警告] {args.info} 已存在，覆盖将丢失已有标注。继续？(y/N): ")
        if answer.strip().lower() != "y":
            print("已取消。")
            sys.exit(0)

    frames_info = build_index_from_folder(args.folder)

    os.makedirs(os.path.dirname(args.info) or ".", exist_ok=True)
    with open(args.info, "w", encoding="utf-8") as f:
        json.dump(frames_info, f, ensure_ascii=False, indent=2)

    print(f"📄 索引已保存到 {args.info}")
    print(f"\n下一步：运行标注工具")
    print(f"  python scripts/2_annotate_cli.py --info {args.info}")


if __name__ == "__main__":
    main()
