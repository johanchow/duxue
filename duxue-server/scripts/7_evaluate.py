"""
效果评估工具
对照人工标注的地面真值，评估 VLM 描述质量和分类层准确率。

用法：
  # 评估分类准确率（需要提供带标签的标注文件）
  python scripts/evaluate.py \
      --predictions data/predictions.json \
      --ground-truth data/ground_truth.jsonl

  # 预构建 Embedding 质心缓存
  python scripts/evaluate.py --build-cache

ground_truth.jsonl 格式（每行一条）：
  {"filepath": "data/frames/frame_001000.jpg", "label": "学习"}
  {"filepath": "data/frames/frame_002000.jpg", "label": "离开"}
"""

import json
import argparse
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))


# ──────────────────────────────────────────────
# 分类评估
# ──────────────────────────────────────────────

def evaluate_classification(predictions: list[dict], ground_truth: dict[str, str]):
    """
    计算分类准确率、每类的 Precision/Recall/F1。

    predictions: [{"filepath":..., "label":...}, ...]
    ground_truth: {filepath: true_label}
    """
    try:
        from sklearn.metrics import classification_report, confusion_matrix
    except ImportError:
        print("[错误] 请安装 scikit-learn：pip install scikit-learn")
        sys.exit(1)

    y_true, y_pred = [], []
    not_found = 0

    for pred in predictions:
        fp = pred["filepath"]
        if fp not in ground_truth:
            not_found += 1
            continue
        y_true.append(ground_truth[fp])
        y_pred.append(pred["label"])

    if not_found > 0:
        print(f"[警告] {not_found} 条预测在 ground_truth 中未找到对应项")

    if not y_true:
        print("[错误] 没有可对比的数据，请检查 filepath 是否一致")
        sys.exit(1)

    accuracy = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)

    print(f"\n{'='*50}")
    print(f"   分类评估报告（样本数：{len(y_true)}）")
    print(f"{'='*50}")
    print(f"整体准确率：{accuracy*100:.1f}%\n")
    print(classification_report(y_true, y_pred, zero_division=0))

    # 混淆矩阵
    labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels)
    print("混淆矩阵（行=真实，列=预测）：")
    header = f"{'':12}" + "".join(f"{l:12}" for l in labels)
    print(header)
    for i, row_label in enumerate(labels):
        row_str = f"{row_label:12}" + "".join(f"{cm[i][j]:12}" for j in range(len(labels)))
        print(row_str)

    return accuracy


# ──────────────────────────────────────────────
# VLM 描述质量评估
# ──────────────────────────────────────────────

def evaluate_description_quality(predictions: list[dict]):
    """
    分析 VLM 描述的基本质量指标（长度分布）。
    不需要人工标注，直接从 predictions.json 分析。
    """
    descriptions = [p.get("description", "") for p in predictions if p.get("description")]

    if not descriptions:
        print("[警告] 无有效描述数据")
        return

    lengths = [len(d) for d in descriptions]
    avg_len = sum(lengths) / len(lengths)
    short   = sum(1 for l in lengths if l < 10)
    empty   = sum(1 for d in descriptions if not d.strip())

    print(f"\n{'='*50}")
    print(f"   VLM 描述质量统计（样本数：{len(descriptions)}）")
    print(f"{'='*50}")
    print(f"平均长度：{avg_len:.0f} 字")
    print(f"最短：{min(lengths)} 字  最长：{max(lengths)} 字")
    print(f"过短（<10字）：{short} 条  ({short/len(descriptions)*100:.1f}%)")
    print(f"空白：{empty} 条")

    if short > len(descriptions) * 0.1:
        print(f"\n⚠️  超过 10% 的描述过短，可能存在模型未响应的情况，建议检查")

    # 标签分布
    label_counts = defaultdict(int)
    for p in predictions:
        if p.get("label"):
            label_counts[p["label"]] += 1

    total = sum(label_counts.values()) or 1
    print(f"\n类别分布：")
    for label, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
        print(f"  {label:<12}  {cnt:>4} 帧  ({cnt/total*100:.1f}%)")


# ──────────────────────────────────────────────
# 预构建 Embedding 质心缓存
# ──────────────────────────────────────────────

def build_centroids_cache():
    from importlib import import_module
    EmbeddingClassifier = import_module("5_classify").EmbeddingClassifier

    cache_path = str(ROOT / "classifier" / "embeddings" / "centroids.json")
    categories_file = str(ROOT / "classifier" / "categories.yaml")

    clf = EmbeddingClassifier(categories_file=categories_file)
    clf.save_centroids(cache_path)
    print(f"\n✅ 质心缓存已生成：{cache_path}")
    print("后续推理可用 --cache 参数直接加载，跳过重复计算")


# ──────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="效果评估工具")
    parser.add_argument("--predictions",   default="data/predictions.json",
                        help="推理输出的预测结果文件")
    parser.add_argument("--ground-truth",  default=None,
                        help="人工标注的真实标签文件（.jsonl，每行含 filepath + label）")
    parser.add_argument("--build-cache",   action="store_true",
                        help="预构建 Embedding 质心缓存文件")
    args = parser.parse_args()

    if args.build_cache:
        build_centroids_cache()
        return

    # 加载预测结果
    try:
        with open(args.predictions, encoding="utf-8") as f:
            predictions = json.load(f)
    except FileNotFoundError:
        print(f"[错误] 预测文件不存在：{args.predictions}")
        print("请先运行：python scripts/inference.py ...")
        sys.exit(1)

    # 描述质量评估（无需 ground truth）
    evaluate_description_quality(predictions)

    # 分类准确率评估（需要 ground truth）
    if args.ground_truth:
        try:
            ground_truth = {}
            with open(args.ground_truth, encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line.strip())
                    ground_truth[obj["filepath"]] = obj["label"]
            print(f"\n[加载] ground_truth：{len(ground_truth)} 条")
        except FileNotFoundError:
            print(f"[错误] ground_truth 文件不存在：{args.ground_truth}")
            sys.exit(1)

        evaluate_classification(predictions, ground_truth)
    else:
        print(f"\n提示：若要评估分类准确率，请提供 --ground-truth 标注文件")
        print(f"  格式（每行）：{{\"filepath\": \"data/frames/frame_xxx.jpg\", \"label\": \"学习\"}}")


if __name__ == "__main__":
    main()
