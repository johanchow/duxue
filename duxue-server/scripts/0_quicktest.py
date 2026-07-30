"""
步骤 0：零样本快速验证（跳过训练，直接测试整体流程）
用基础模型（不微调）测试一张或多张图片，观察：
  1. 结构化 JSON 输出是否合理
  2. 第二阶段分类结果是否正确
  3. 整体流程是否跑通

支持两种运行方式：
  A. Qwen API（推荐先试，无需本地 GPU）
       python scripts/0_quicktest.py --image data/frames/xxx.jpg --mode api

  B. 本地模型（需要显存，加载较慢）
       python scripts/0_quicktest.py --image data/frames/xxx.jpg --mode local \
           --model Qwen/Qwen2.5-VL-7B-Instruct

  C. 批量测试整个文件夹（输出汇总表格）
       python scripts/0_quicktest.py --folder data/frames --mode api
"""

import json
import os
import sys
import argparse
import base64
from pathlib import Path


# ── 与 3_prepare_dataset.py 保持一致的 Prompt ──
STRUCTURED_PROMPT = """请观察这张图片，用结构化 JSON 描述图中学生的行为状态。

要求：
- 输出合法的 JSON，不要包含任何其他文字
- 每个字段用简短的自然语言短句描述，不要使用固定词表
- 看不清的字段写 "不可见"

输出格式：
{
  "body_pos":    "人物整体姿态描述",
  "head_pose":   "头部方向和角度描述",
  "gaze_target": "目光注视目标描述",
  "hand_action": "手部动作描述",
  "desk_object": "桌面可见物品描述",
  "seat_status": "是否在座位上的描述",
  "motion_state":"当前动作是否持续稳定",
  "desc_summary":"一句话整体摘要"
}"""


# ──────────────────────────────────────────────
# 方式 A：Qwen API
# ──────────────────────────────────────────────

def call_qwen_api(image_path: str, model: str = "qwen-vl-max") -> str:
    """通过 Qwen API 获取结构化描述（需要设置 DASHSCOPE_API_KEY 环境变量）"""
    try:
        from openai import OpenAI
    except ImportError:
        print("[错误] 请安装 openai 包：pip install openai")
        sys.exit(1)

    api_key = os.environ.get("DASHSCOPE_API_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("[错误] 请设置环境变量：export DASHSCOPE_API_KEY=your_key")
        print("  阿里云 DashScope 控制台：https://dashscope.aliyun.com")
        sys.exit(1)

    client = OpenAI(
        api_key=api_key,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
    )

    # 将图片转为 base64
    with open(image_path, "rb") as f:
        img_b64 = base64.b64encode(f.read()).decode()

    suffix = Path(image_path).suffix.lower().lstrip(".")
    mime   = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "webp": "webp"}.get(suffix, "jpeg")

    response = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{img_b64}"}},
                {"type": "text",      "text": STRUCTURED_PROMPT}
            ]
        }],
        max_tokens=300,
        temperature=0,
    )
    return response.choices[0].message.content.strip()


# ──────────────────────────────────────────────
# 方式 B：本地模型
# ──────────────────────────────────────────────

def call_local_model(image_path: str, model_path: str) -> str:
    """本地加载模型推理"""
    import torch
    from PIL import Image
    from transformers import AutoProcessor

    try:
        from transformers import Qwen2_5_VLForConditionalGeneration as VLModel
    except ImportError:
        from transformers import Qwen2VLForConditionalGeneration as VLModel

    print(f"[本地模型] 加载中：{model_path}（首次加载较慢）...")
    model = VLModel.from_pretrained(model_path, torch_dtype="auto", device_map="auto")
    processor = AutoProcessor.from_pretrained(model_path)
    model.eval()

    image = Image.open(image_path).convert("RGB")
    messages = [{
        "role": "user",
        "content": [
            {"type": "image",  "image": image},
            {"type": "text",   "text": STRUCTURED_PROMPT}
        ]
    }]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=[image], return_tensors="pt").to(model.device)

    with torch.no_grad():
        output_ids = model.generate(**inputs, max_new_tokens=300, do_sample=False,
                                    temperature=None, top_p=None)
    return processor.decode(
        output_ids[0][inputs.input_ids.shape[1]:], skip_special_tokens=True
    ).strip()


# ──────────────────────────────────────────────
# 解析 JSON 输出（容错）
# ──────────────────────────────────────────────

def parse_json_output(raw: str) -> dict | None:
    """从模型输出中提取 JSON（处理可能的前后缀文字）"""
    raw = raw.strip()

    # 直接解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 提取第一个 {...} 块
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError:
            pass

    return None


# ──────────────────────────────────────────────
# 尝试运行第二阶段分类（可选）
# ──────────────────────────────────────────────

def try_classify(structured: dict) -> str | None:
    """如果 classifier/ 配置存在，尝试用规则分类"""
    rules_file = Path(__file__).parent.parent / "classifier" / "rules.yaml"
    if not rules_file.exists():
        return None

    try:
        from importlib import import_module
        clf_module = import_module("5_classify")
        clf = clf_module.RuleClassifier(str(rules_file))

        # 把结构化字段拼成一句描述供规则匹配
        combined = " ".join(v for v in structured.values() if isinstance(v, str))
        label, conf = clf.classify(combined)
        return f"{label}（置信度 {conf}）"
    except Exception:
        return None


# ──────────────────────────────────────────────
# 单图测试
# ──────────────────────────────────────────────

def test_single(image_path: str, mode: str, model: str) -> dict | None:
    print(f"\n{'─'*50}")
    print(f"图片：{image_path}")

    if mode == "api":
        raw = call_qwen_api(image_path, model)
    else:
        raw = call_local_model(image_path, model)

    print(f"\n── 模型原始输出 ──\n{raw}")

    parsed = parse_json_output(raw)
    if parsed:
        print(f"\n── 解析结果 ──")
        for k, v in parsed.items():
            print(f"  {k:14}: {v}")

        label = try_classify(parsed)
        if label:
            print(f"\n── 第二阶段分类 ──\n  → {label}")
    else:
        print("\n⚠️  JSON 解析失败，模型输出不是合法 JSON")
        print("  提示：基础模型有时输出带额外说明文字，微调后会更稳定")

    return parsed


# ──────────────────────────────────────────────
# 主函数
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="零样本快速验证")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--image",  help="单张图片路径")
    src.add_argument("--folder", help="批量测试文件夹")
    parser.add_argument("--mode",  default="api",   choices=["api", "local"],
                        help="推理方式：api（默认）或 local")
    parser.add_argument("--model", default="qwen-vl-max",
                        help="API 模式下的模型名（默认 qwen-vl-max），"
                             "local 模式下填本地路径或 HuggingFace 模型名")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent))

    if args.image:
        test_single(args.image, args.mode, args.model)

    else:
        exts = {".jpg", ".jpeg", ".png", ".webp"}
        images = sorted(p for p in Path(args.folder).iterdir() if p.suffix.lower() in exts)
        if not images:
            print(f"[错误] 文件夹内无图片：{args.folder}")
            sys.exit(1)

        print(f"批量测试 {len(images)} 张图片（mode={args.mode}）\n")
        results = []
        for img in images:
            parsed = test_single(str(img), args.mode, args.model)
            results.append({"image": img.name, "parsed": parsed})

        # 统计 JSON 解析成功率
        success = sum(1 for r in results if r["parsed"])
        print(f"\n{'='*50}")
        print(f"解析成功率：{success}/{len(results)} ({success/len(results)*100:.0f}%)")
        if success < len(results):
            print("提示：解析失败说明基础模型输出不够规范，微调后会改善")


if __name__ == "__main__":
    main()
