"""
第三步：整理训练数据
将人工标注结果转换为 Qwen3-VL 微调所需的对话格式，
按 9:1 划分训练集和验证集，打印数据分布统计。

用法：
  python scripts/prepare_dataset.py --info data/frames_info.json
"""

import json
import random
import argparse
from pathlib import Path
from collections import Counter


# 训练时使用的固定 Prompt（推理时保持一致）
DESCRIBE_PROMPT = (
    "请观察这张图片，用 1~2 句话客观描述图中学生的行为状态。"
    "需要涵盖：头部姿态、手部动作、目光方向、桌面物品、人物位置。"
    "只描述可见内容，不做行为判断。"
)


def load_annotations(frames_info_file: str) -> list[dict]:
    """从 frames_info.json 加载已标注的条目"""
    with open(frames_info_file, encoding="utf-8") as f:
        frames = json.load(f)

    valid = [f for f in frames if f.get("description", "").strip()]
    skipped = len(frames) - len(valid)

    print(f"总帧数：{len(frames)}，有效标注：{len(valid)}，跳过（空白）：{skipped}")
    return valid


def convert_to_training_format(annotations: list[dict]) -> list[dict]:
    """
    转换为 Qwen3-VL 对话格式：
    {
      "messages": [
        { "role": "user",      "content": [{"type":"image",...}, {"type":"text",...}] },
        { "role": "assistant", "content": "行为描述文字" }
      ]
    }
    """
    dataset = []
    for ann in annotations:
        record = {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "image": ann["filepath"]
                        },
                        {
                            "type": "text",
                            "text": DESCRIBE_PROMPT
                        }
                    ]
                },
                {
                    "role": "assistant",
                    "content": ann["description"].strip()
                }
            ]
        }
        dataset.append(record)
    return dataset


def split_and_save(dataset: list[dict], output_dir: str, split_ratio: float = 0.9):
    """随机打乱后按比例划分，保存为 JSONL"""
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    random.shuffle(dataset)
    split_idx = int(len(dataset) * split_ratio)
    train_data = dataset[:split_idx]
    val_data   = dataset[split_idx:]

    train_file = f"{output_dir}/dataset_train.jsonl"
    val_file   = f"{output_dir}/dataset_val.jsonl"

    _write_jsonl(train_file, train_data)
    _write_jsonl(val_file, val_data)

    print(f"\n训练集：{len(train_data)} 条  →  {train_file}")
    print(f"验证集：{len(val_data)} 条  →  {val_file}")
    return train_file, val_file


def _write_jsonl(filepath: str, data: list[dict]):
    with open(filepath, "w", encoding="utf-8") as f:
        for item in data:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def check_quality(annotations: list[dict]):
    """打印描述文字长度分布，辅助判断标注质量"""
    lengths = [len(a["description"]) for a in annotations]
    avg_len = sum(lengths) / len(lengths)
    short = sum(1 for l in lengths if l < 15)

    print(f"\n描述长度统计：平均 {avg_len:.0f} 字，最短 {min(lengths)} 字，最长 {max(lengths)} 字")
    if short > 0:
        print(f"⚠️  有 {short} 条描述少于 15 字，建议补充更多细节")


def print_llamafactory_tip(train_file: str, val_file: str):
    """打印 LLaMA-Factory 数据集注册提示"""
    print("\n" + "="*60)
    print("下一步：注册数据集并启动训练")
    print("="*60)
    print("\n1. 在 LLaMA-Factory/data/dataset_info.json 中新增：")
    print("""
{
  "student_behavior_desc": {
    "file_name": \"""" + train_file + """\",
    "formatting": "sharegpt",
    "columns": {"messages": "messages"},
    "tags": {
      "role_tag": "role", "content_tag": "content",
      "user_tag": "user", "assistant_tag": "assistant"
    }
  }
}
""")
    print("2. 运行训练脚本：")
    print("   bash scripts/train.sh")


def main():
    parser = argparse.ArgumentParser(description="整理训练数据")
    parser.add_argument("--info",   default="data/frames_info.json", help="帧索引文件（含标注）")
    parser.add_argument("--output", default="data",                  help="输出目录")
    parser.add_argument("--ratio",  type=float, default=0.9,         help="训练集比例，默认 0.9")
    parser.add_argument("--seed",   type=int,   default=42,          help="随机种子")
    args = parser.parse_args()

    random.seed(args.seed)

    print("=== 整理训练数据 ===\n")
    annotations = load_annotations(args.info)

    if len(annotations) < 30:
        print(f"\n⚠️  标注数量不足（{len(annotations)} 条），建议至少标注 150 条再训练")

    check_quality(annotations)

    dataset = convert_to_training_format(annotations)
    train_file, val_file = split_and_save(dataset, args.output, args.ratio)

    print_llamafactory_tip(train_file, val_file)


if __name__ == "__main__":
    main()
