"""
第二步：人工标注工具（命令行版）
逐帧打开图片，人工输入行为描述文字，实时保存进度，支持中断后继续。

用法：
  python scripts/annotate_cli.py --info data/frames_info.json

标注规范（描述应包含以下维度，有则写，无则忽略）：
  - 头部姿态：低下/抬起/偏转方向和角度
  - 手部动作：握笔/翻书/摆弄玩具/静止
  - 目光方向：看书/看别处/看屏幕/眼睛闭合
  - 桌面物品：书本/铅笔/玩具/手机/无
  - 人物位置：坐在座位/站起/离开画面

示例描述：
  "学生头部低下约 45°，右手握笔在练习本上横向书写，桌面可见课本和铅笔"
  "学生不在座位，画面中无人"
  "学生坐在座位上，头部抬起朝向右侧，手中握着一个积木玩具"
"""

import json
import os
import sys
import platform
import argparse
from pathlib import Path


def open_image(filepath: str):
    """用系统默认图片查看器打开图片"""
    system = platform.system()
    if system == "Darwin":       # macOS
        os.system(f"open '{filepath}'")
    elif system == "Linux":
        os.system(f"eog '{filepath}' &>/dev/null &")
    elif system == "Windows":
        os.system(f"start '{filepath}'")


def print_stats(frames: list):
    """打印标注进度统计"""
    total = len(frames)
    labeled = sum(1 for f in frames if f.get("description"))
    print(f"\n📊 标注进度：{labeled}/{total} ({labeled/total*100:.1f}%)")


def annotate(frames_info_file: str, start_from: int = 0):
    """
    主标注循环。

    Args:
        frames_info_file: frames_info.json 路径
        start_from:       从第几条开始（0-indexed），用于跳过
    """
    if not os.path.exists(frames_info_file):
        print(f"[错误] 文件不存在：{frames_info_file}")
        sys.exit(1)

    with open(frames_info_file, encoding="utf-8") as f:
        frames = json.load(f)

    # 找出所有未标注的帧
    pending = [(i, f) for i, f in enumerate(frames) if not f.get("description")]

    if not pending:
        print("✅ 所有帧已标注完毕！")
        print_stats(frames)
        return

    print(f"\n=== 学生行为标注工具 ===")
    print(f"总帧数：{len(frames)}，待标注：{len(pending)}")
    print(f"\n操作说明：")
    print(f"  输入描述文字后回车 → 保存并继续下一帧")
    print(f"  直接回车（空白）   → 跳过此帧")
    print(f"  输入 q 后回车      → 保存并退出")
    print(f"  Ctrl+C             → 紧急退出（已保存的不丢失）")
    print()

    saved_count = 0

    try:
        for seq, (original_idx, frame) in enumerate(pending):
            if seq < start_from:
                continue

            print(f"[{seq+1}/{len(pending)}] 时间戳：{frame['time_str']}  "
                  f"文件：{Path(frame['filepath']).name}")

            open_image(frame["filepath"])

            desc = input("描述：").strip()

            if desc.lower() == "q":
                print("\n保存并退出...")
                break
            elif desc == "":
                print("  → 已跳过")
                continue
            else:
                frames[original_idx]["description"] = desc
                saved_count += 1
                print(f"  → ✅ 已保存")

            # 每标注 10 条，写回文件一次（防止意外丢失）
            if saved_count % 10 == 0:
                _save(frames_info_file, frames)
                print(f"  [自动保存，已标注 {saved_count} 条]")

    except KeyboardInterrupt:
        print("\n\n[中断] 正在保存...")

    _save(frames_info_file, frames)
    print_stats(frames)
    print(f"\n下一步：整理训练数据")
    print(f"  python scripts/prepare_dataset.py --info {frames_info_file}")


def _save(filepath: str, frames: list):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(frames, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description="人工标注工具")
    parser.add_argument("--info",  default="data/frames_info.json", help="帧索引文件路径")
    parser.add_argument("--skip",  type=int, default=0, help="跳过前 N 条（从第 N+1 条开始）")
    args = parser.parse_args()

    annotate(args.info, start_from=args.skip)


if __name__ == "__main__":
    main()
