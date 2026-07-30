#!/bin/bash
# 第四步：微调 Qwen3-VL（第一阶段行为描述器）
# 需要先安装 LLaMA-Factory 并注册数据集（见 prepare_dataset.py 的输出提示）
#
# 使用方式：
#   bash scripts/train.sh              # 云 GPU / Linux 标准训练
#   bash scripts/train.sh --mac        # Mac 本地实验（使用 mlx-vlm）
#
# 环境要求：
#   - Python 3.10+
#   - llamafactory: pip install llamafactory
#   - GPU: RTX 4090 (24GB) 或 A100

set -e

# ============================
# 配置区（按需修改）
# ============================
MODEL_NAME="Qwen/Qwen3-VL-7B-Instruct"   # HuggingFace 模型名
DATASET="student_behavior_desc"            # 在 dataset_info.json 中注册的名称
OUTPUT_DIR="./output/qwen3vl_describer"
DATA_DIR="./data"

LORA_RANK=8
LORA_TARGET="q_proj,k_proj,v_proj,o_proj"   # 覆盖完整注意力层
LEARNING_RATE="2e-4"
NUM_EPOCHS=3
BATCH_SIZE=1
GRAD_ACCUM=8                                # 等效 batch_size = 8

# ============================
# Mac 本地实验（mlx-vlm）
# ============================
if [[ "$1" == "--mac" ]]; then
    echo "=== Mac 本地实验模式（mlx-vlm）==="
    echo "注意：Mac 版仅用于验证流程，建议限制图片分辨率"

    pip install mlx-vlm -q

    python -m mlx_vlm.lora \
        --model "mlx-community/Qwen3-VL-7B-Instruct-4bit" \
        --data "$DATA_DIR" \
        --train \
        --batch-size 1 \
        --lora-layers 8 \
        --grad-checkpoint \
        --max-seq-length 1024 \
        --iters 500 \
        --learning-rate 2e-5 \
        --steps-per-eval 100 \
        --adapter-path "$OUTPUT_DIR/adapters_mac"

    echo ""
    echo "✅ Mac 实验训练完成，权重保存在 $OUTPUT_DIR/adapters_mac"
    echo "（Mac 版 adapter 无法直接合并，推理时需用 mlx 加载）"
    exit 0
fi

# ============================
# 云 GPU 标准训练（LLaMA-Factory）
# ============================
echo "=== 云 GPU 训练模式（LLaMA-Factory + QLoRA）==="

# 检查 llamafactory 是否安装
if ! python -c "import llamafactory" &>/dev/null; then
    echo "[错误] 请先安装 LLaMA-Factory："
    echo "  pip install llamafactory"
    exit 1
fi

llamafactory-cli train \
    --model_name_or_path "$MODEL_NAME" \
    --model_type qwen3_vl \
    --stage sft \
    --do_train \
    --finetuning_type lora \
    --lora_rank $LORA_RANK \
    --lora_target "$LORA_TARGET" \
    --lora_dropout 0.05 \
    --dataset "$DATASET" \
    --template qwen3_vl \
    --cutoff_len 2048 \
    --max_samples 100000 \
    --per_device_train_batch_size $BATCH_SIZE \
    --gradient_accumulation_steps $GRAD_ACCUM \
    --num_train_epochs $NUM_EPOCHS \
    --learning_rate $LEARNING_RATE \
    --lr_scheduler_type cosine \
    --warmup_ratio 0.05 \
    --bf16 \
    --flash_attn fa2 \
    --val_size 0.1 \
    --eval_strategy steps \
    --eval_steps 50 \
    --output_dir "$OUTPUT_DIR/lora_weights" \
    --logging_steps 10 \
    --save_steps 100 \
    --save_total_limit 3 \
    --plot_loss \
    --report_to none

echo ""
echo "✅ 训练完成！"
echo ""
echo "下一步：合并 LoRA 权重"
echo "  llamafactory-cli export \\"
echo "    --model_name_or_path $MODEL_NAME \\"
echo "    --adapter_name_or_path $OUTPUT_DIR/lora_weights \\"
echo "    --template qwen3_vl \\"
echo "    --finetuning_type lora \\"
echo "    --export_dir $OUTPUT_DIR/merged \\"
echo "    --export_size 2"
