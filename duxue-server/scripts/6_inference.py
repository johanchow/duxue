"""
第六步：全流程批量推理 + 时间轴生成
使用微调后的 Qwen3-VL（第一阶段）生成行为描述，
再经过分类层（第二阶段）输出类别，最终生成行为时间轴。

用法：
  # 完整推理（从帧图片到时间轴）
  python scripts/inference.py \
      --model output/qwen3vl_describer/merged \
      --frames data/frames_info.json \
      --method auto

  # 仅重新分类（VLM 描述已存在，跳过第一阶段）
  python scripts/inference.py \
      --reclassify \
      --predictions data/predictions.json \
      --method embedding
"""

import json
import os
import sys
import argparse
from pathlib import Path
from collections import Counter

import torch
from PIL import Image
from tqdm import tqdm

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from importlib import import_module
build_classifier = import_module("5_classify").build_classifier

# 与训练时保持完全一致的 Prompt
DESCRIBE_PROMPT = (
    "请观察这张图片，用 1~2 句话客观描述图中学生的行为状态。"
    "需要涵盖：头部姿态、手部动作、目光方向、桌面物品、人物位置。"
    "只描述可见内容，不做行为判断。"
)


# ──────────────────────────────────────────────
# 加载 VLM 模型
# ──────────────────────────────────────────────

def load_vlm(model_path: str):
    """
    加载微调后的 Qwen3-VL 模型和处理器。
    兼容 Qwen2-VL / Qwen2.5-VL / Qwen3-VL 各版本。
    """
    from transformers import AutoProcessor

    # 兼容不同版本的 transformers
    try:
        from transformers import Qwen2_5_VLForConditionalGeneration as VLModel
    except ImportError:
        try:
            from transformers import Qwen2VLForConditionalGeneration as VLModel
        except ImportError:
            from transformers import AutoModelForCausalLM as VLModel

    print(f"[VLM] 加载模型：{model_path}")
    model = VLModel.from_pretrained(
        model_path,
        torch_dtype=torch.bfloat16,
        device_map="auto"
    )
    processor = AutoProcessor.from_pretrained(model_path)
    model.eval()
    print(f"[VLM] 模型加载完成，设备：{next(model.parameters()).device}")
    return model, processor


def describe_frame(model, processor, image_path: str) -> str:
    """第一阶段：用 VLM 生成单帧的行为描述文字"""
    image = Image.open(image_path).convert("RGB")

    messages = [{
        "role": "user",
        "content": [
            {"type": "image",  "image": image},
            {"type": "text",   "text": DESCRIBE_PROMPT}
        ]
    }]

    text = processor.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True
    )
    inputs = processor(
        text=[text], images=[image], return_tensors="pt"
    ).to(model.device)

    with torch.no_grad():
        output_ids = model.generate(
            **inputs,
            max_new_tokens=100,
            do_sample=False,       # 描述任务用贪心解码，保证稳定性
            temperature=None,
            top_p=None,
        )

    generated = processor.decode(
        output_ids[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True
    ).strip()
    return generated


# ──────────────────────────────────────────────
# 时序后处理
# ──────────────────────────────────────────────

def smooth_labels(predictions: list[dict], window: int = 3) -> list[dict]:
    """
    滑动窗口多数投票，消除孤立噪声帧。
    window: 前后各取 window 帧，共 2*window+1 帧投票。
    """
    smoothed = []
    labels = [p["label"] for p in predictions]
    n = len(labels)

    for i, pred in enumerate(predictions):
        lo = max(0, i - window)
        hi = min(n, i + window + 1)
        window_labels = labels[lo:hi]
        majority = Counter(window_labels).most_common(1)[0][0]
        smoothed.append({**pred, "label": majority})

    return smoothed


def merge_segments(predictions: list[dict], min_duration_sec: int = 10) -> list[dict]:
    """
    将连续相同标签的帧合并为时间段。
    min_duration_sec: 过短的片段（秒）直接丢弃，避免碎片化。
    """
    if not predictions:
        return []

    predictions = sorted(predictions, key=lambda x: x["timestamp"])
    segments = []
    cur_label = predictions[0]["label"]
    cur_start = predictions[0]["timestamp"]
    cur_end   = predictions[0]["timestamp"]

    for pred in predictions[1:]:
        if pred["label"] == cur_label:
            cur_end = pred["timestamp"]
        else:
            if cur_end - cur_start >= min_duration_sec:
                segments.append({
                    "start":    cur_start,
                    "end":      cur_end,
                    "label":    cur_label,
                    "duration": round(cur_end - cur_start, 1)
                })
            cur_label = pred["label"]
            cur_start = pred["timestamp"]
            cur_end   = pred["timestamp"]

    # 最后一段
    if cur_end - cur_start >= min_duration_sec:
        segments.append({
            "start":    cur_start,
            "end":      cur_end,
            "label":    cur_label,
            "duration": round(cur_end - cur_start, 1)
        })

    return segments


# ──────────────────────────────────────────────
# 报告生成
# ──────────────────────────────────────────────

def fmt_time(sec: float) -> str:
    h, m, s = int(sec // 3600), int((sec % 3600) // 60), int(sec % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def print_report(segments: list[dict], categories_file: str = None):
    """打印可读的时间轴报告和统计摘要"""
    # 加载类别图标
    icons = {"学习": "📖", "离开": "🚶", "走神/玩耍": "🎮"}
    if categories_file and os.path.exists(categories_file):
        import yaml
        with open(categories_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)
        for cat in config.get("categories", []):
            icons[cat["label"]] = cat.get("icon", "❓")

    print("\n" + "="*50)
    print("           学习行为时间轴")
    print("="*50)

    totals: dict[str, float] = {}
    for seg in segments:
        label    = seg["label"]
        duration = seg["duration"]
        icon     = icons.get(label, "❓")
        print(f"{fmt_time(seg['start'])} → {fmt_time(seg['end'])}  "
              f"{icon} {label:<10}  ({int(duration//60)}分{int(duration%60)}秒)")
        totals[label] = totals.get(label, 0) + duration

    total_sec = sum(totals.values()) or 1
    print("\n" + "="*50)
    print("           统计摘要")
    print("="*50)
    for label, sec in sorted(totals.items(), key=lambda x: -x[1]):
        icon = icons.get(label, "❓")
        print(f"{icon} {label:<10}  {int(sec//60):>3}分{int(sec%60):02d}秒  "
              f"({sec/total_sec*100:.1f}%)")


# ──────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────

def run_inference(args):
    """完整两阶段推理"""
    # 加载帧索引
    with open(args.frames, encoding="utf-8") as f:
        frames_info = json.load(f)
    print(f"[推理] 共 {len(frames_info)} 帧待处理")

    # 加载 VLM（第一阶段）
    model, processor = load_vlm(args.model)

    # 加载分类器（第二阶段）
    clf = build_classifier(
        method=args.method,
        centroids_cache=args.cache
    )

    predictions = []
    for frame in tqdm(frames_info, desc="推理中"):
        if not os.path.exists(frame["filepath"]):
            print(f"[警告] 帧文件不存在，跳过：{frame['filepath']}")
            continue

        # 第一阶段：VLM 生成行为描述
        description = describe_frame(model, processor, frame["filepath"])

        # 第二阶段：分类层映射到类别
        label, confidence = clf.classify(description)

        predictions.append({
            "timestamp":   frame["timestamp"],
            "time_str":    frame["time_str"],
            "filepath":    frame["filepath"],
            "description": description,
            "label":       label,
            "confidence":  confidence
        })

    return predictions


def run_reclassify(args):
    """仅重新分类（跳过 VLM，使用已有的描述）"""
    with open(args.predictions, encoding="utf-8") as f:
        predictions = json.load(f)
    print(f"[重分类] 加载 {len(predictions)} 条已有预测，仅重新分类")

    clf = build_classifier(method=args.method, centroids_cache=args.cache)

    for pred in tqdm(predictions, desc="重分类"):
        label, confidence = clf.classify(pred["description"])
        pred["label"]      = label
        pred["confidence"] = confidence

    return predictions


def main():
    parser = argparse.ArgumentParser(description="学生行为分析推理")
    # 模式选择
    parser.add_argument("--reclassify",  action="store_true",
                        help="仅重新分类（复用已有描述，跳过 VLM 推理）")
    # 输入
    parser.add_argument("--model",       default="output/qwen3vl_describer/merged",
                        help="微调后模型路径")
    parser.add_argument("--frames",      default="data/frames_info.json",
                        help="帧索引文件路径")
    parser.add_argument("--predictions", default="data/predictions.json",
                        help="已有预测文件（--reclassify 时使用）")
    # 分类层
    parser.add_argument("--method",      default="auto",
                        help="分类方式：rules / embedding / auto")
    parser.add_argument("--cache",       default="classifier/embeddings/centroids.json",
                        help="质心向量缓存文件（embedding 方式）")
    # 后处理
    parser.add_argument("--smooth",      type=int, default=3,
                        help="滑动窗口大小（帧数），0 表示不平滑")
    parser.add_argument("--min-seg",     type=int, default=10,
                        help="最小时间段长度（秒），过短片段被过滤")
    # 输出
    parser.add_argument("--output-pred", default="data/predictions.json",
                        help="逐帧预测结果输出路径")
    parser.add_argument("--output-tl",   default="data/timeline.json",
                        help="时间轴输出路径")
    args = parser.parse_args()

    # ── 推理 ──
    if args.reclassify:
        predictions = run_reclassify(args)
    else:
        predictions = run_inference(args)

    # ── 保存逐帧结果 ──
    os.makedirs("data", exist_ok=True)
    with open(args.output_pred, "w", encoding="utf-8") as f:
        json.dump(predictions, f, ensure_ascii=False, indent=2)
    print(f"\n[保存] 逐帧预测 → {args.output_pred}")

    # ── 时序后处理 ──
    if args.smooth > 0:
        predictions = smooth_labels(predictions, window=args.smooth)

    segments = merge_segments(predictions, min_duration_sec=args.min_seg)

    # ── 保存时间轴 ──
    with open(args.output_tl, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"[保存] 行为时间轴 → {args.output_tl}")

    # ── 打印报告 ──
    print_report(segments, categories_file="classifier/categories.yaml")


if __name__ == "__main__":
    main()
