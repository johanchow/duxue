"""
第五步：第二阶段分类层
将 VLM 输出的行为描述文字映射到具体的行为类别。
支持三种方式，可在推理时通过 --method 参数切换：

  rules     : 关键词规则匹配（最快，零依赖）
  embedding : 文本嵌入相似度（推荐，泛化好）
  auto      : 先用 rules，无命中时 fallback 到 embedding（综合推荐）

用法（独立测试）：
  python scripts/classify.py --desc "学生右手握笔在纸上书写" --method embedding
"""

import os
import sys
import json
import yaml
import argparse
import numpy as np
from pathlib import Path

ROOT = Path(__file__).parent.parent


# ──────────────────────────────────────────────
# 方式 1：关键词规则匹配
# ──────────────────────────────────────────────

class RuleClassifier:
    def __init__(self, rules_file: str = None):
        rules_file = rules_file or str(ROOT / "classifier" / "rules.yaml")
        with open(rules_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.rules = sorted(config["rules"], key=lambda r: -r["priority"])
        self.default_label = config.get("default_label", "走神/玩耍")

    def classify(self, description: str) -> tuple[str, float]:
        """
        Returns:
            (label, confidence)  confidence 为 1.0（规则命中）或 0.0（fallback）
        """
        desc = description.lower()

        for rule in self.rules:
            # 检查 any_of（至少一个关键词命中）
            any_hit = any(kw in desc for kw in rule.get("any_of", []))
            if not any_hit:
                continue

            # 检查 none_of（排除条件）
            none_hit = any(kw in desc for kw in rule.get("none_of", []))
            if none_hit:
                continue

            return rule["label"], 1.0

        return self.default_label, 0.0


# ──────────────────────────────────────────────
# 方式 2：文本嵌入相似度
# ──────────────────────────────────────────────

class EmbeddingClassifier:
    def __init__(self, categories_file: str = None, model_name: str = "BAAI/bge-m3"):
        categories_file = categories_file or str(ROOT / "classifier" / "categories.yaml")

        with open(categories_file, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        self.categories = config["categories"]
        self.fallback_label = next(
            (c["label"] for c in self.categories if c.get("fallback")),
            self.categories[-1]["label"]
        )

        self._model = None
        self._model_name = model_name
        self._centroids: dict[str, np.ndarray] = {}

    def _load_model(self):
        """延迟加载 Embedding 模型（避免不使用时的启动开销）"""
        if self._model is not None:
            return
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError:
            print("[错误] 请安装 sentence-transformers：pip install sentence-transformers")
            sys.exit(1)

        print(f"[Embedding] 加载模型 {self._model_name}...")
        self._model = SentenceTransformer(self._model_name)
        self._build_centroids()
        print(f"[Embedding] 模型加载完成，已为 {len(self._centroids)} 个类别构建参考向量")

    def _build_centroids(self):
        """为每个类别的参考描述计算均值向量（质心）"""
        for cat in self.categories:
            refs = cat["references"]
            embeddings = self._model.encode(refs, normalize_embeddings=True)
            centroid = embeddings.mean(axis=0)
            # 归一化质心向量
            centroid = centroid / np.linalg.norm(centroid)
            self._centroids[cat["label"]] = centroid

    def classify(self, description: str) -> tuple[str, float]:
        """
        Returns:
            (label, confidence)  confidence 为余弦相似度最大值
        """
        self._load_model()

        query_vec = self._model.encode([description], normalize_embeddings=True)[0]

        best_label = self.fallback_label
        best_score = -1.0

        for label, centroid in self._centroids.items():
            score = float(np.dot(query_vec, centroid))
            if score > best_score:
                best_score = score
                best_label = label

        return best_label, round(best_score, 3)

    def save_centroids(self, path: str):
        """保存预计算的质心向量，避免每次重复计算"""
        self._load_model()
        data = {label: vec.tolist() for label, vec in self._centroids.items()}
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f)
        print(f"[Embedding] 质心向量已保存到 {path}")

    def load_centroids(self, path: str):
        """从文件加载已缓存的质心向量（跳过重新计算）"""
        with open(path) as f:
            data = json.load(f)
        self._centroids = {label: np.array(vec) for label, vec in data.items()}
        print(f"[Embedding] 已从缓存加载 {len(self._centroids)} 个类别的质心向量")

        # 仍需加载 model 以便对新描述做 encode
        from sentence_transformers import SentenceTransformer
        self._model = SentenceTransformer(self._model_name)


# ──────────────────────────────────────────────
# 方式 3：Auto（Rules + Embedding fallback）
# ──────────────────────────────────────────────

class AutoClassifier:
    """
    先用规则分类（快），规则无把握时（confidence=0）交给 Embedding 确认。
    """
    def __init__(self, rules_file: str = None, categories_file: str = None):
        self.rule_clf = RuleClassifier(rules_file)
        self.emb_clf  = EmbeddingClassifier(categories_file)

    def classify(self, description: str) -> tuple[str, float]:
        label, conf = self.rule_clf.classify(description)
        if conf > 0:
            return label, conf
        # 规则无命中，交给 embedding 判断
        return self.emb_clf.classify(description)


# ──────────────────────────────────────────────
# 工厂函数：根据 method 参数创建分类器
# ──────────────────────────────────────────────

def build_classifier(method: str = "auto",
                     rules_file: str = None,
                     categories_file: str = None,
                     centroids_cache: str = None) -> RuleClassifier | EmbeddingClassifier | AutoClassifier:
    if method == "rules":
        return RuleClassifier(rules_file)

    elif method == "embedding":
        clf = EmbeddingClassifier(categories_file)
        if centroids_cache and os.path.exists(centroids_cache):
            clf.load_centroids(centroids_cache)
        return clf

    elif method == "auto":
        clf = AutoClassifier(rules_file, categories_file)
        if centroids_cache and os.path.exists(centroids_cache):
            clf.emb_clf.load_centroids(centroids_cache)
        return clf

    else:
        raise ValueError(f"未知的分类方法：{method}，可选 rules / embedding / auto")


# ──────────────────────────────────────────────
# 命令行独立测试
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="分类层独立测试")
    parser.add_argument("--desc",   required=True,       help="待分类的行为描述文字")
    parser.add_argument("--method", default="auto",      help="分类方式：rules / embedding / auto")
    parser.add_argument("--cache",  default=None,        help="质心向量缓存文件路径")
    args = parser.parse_args()

    clf = build_classifier(method=args.method, centroids_cache=args.cache)
    label, confidence = clf.classify(args.desc)

    print(f"\n描述：{args.desc}")
    print(f"分类：{label}（置信度 {confidence:.3f}，方法：{args.method}）")


if __name__ == "__main__":
    main()
