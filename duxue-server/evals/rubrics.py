"""Reusable immutable rubric versions; case-specific expectations stay in data/."""

RUBRICS = {
    "teaching-quality.v1": "结合当前请求、截至本轮历史和原图评实际交付内容。1分：错误或误导；2分：重要内容不符或无帮助；3分：方向正确但不够可执行；4分：正确、切题、适龄且下一步可执行；5分：满足4分并以适量提示保留学生推理空间。事实问答允许直接回答；知识说明、发音、澄清和安全拒绝按各自任务评估，不强求推理提示。",
}


def resolve(ref):
    if ref not in RUBRICS:
        raise ValueError(f"unknown rubric_ref: {ref}")
    return RUBRICS[ref]
