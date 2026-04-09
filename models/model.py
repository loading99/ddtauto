"""
model.py - 数字识别模型定义
提供两种模型：
  1. DigitCNN       - 轻量级自定义 CNN（专为 70×96 非正方形设计）
  2. DigitResNet    - 基于 ResNet18 的迁移学习模型（第一层适配小尺寸）

输入张量尺寸: (B, 3, 70, 96)  ← 原图 48×35 pad 后 ×2
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from torchvision import models


# ─────────────────────────────────────────────
# 方案一：轻量级自定义 CNN（专为 70H×96W 设计）
# ─────────────────────────────────────────────
class DigitCNN(nn.Module):
    """
    专为小尺寸非正方形数字图片设计的轻量 CNN
    输入: (B, 3, 70, 96)  →  输出: (B, 10)
    使用 AdaptiveAvgPool2d 结尾，对尺寸变化鲁棒
    参数量 ~350K，训练速度快
    """

    def __init__(self, num_classes=10, dropout=0.4):
        super().__init__()

        self.features = nn.Sequential(
            # Block 1: 70×96 → 35×48
            nn.Conv2d(3, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.Conv2d(32, 32, 3, padding=1), nn.BatchNorm2d(32), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(0.1),

            # Block 2: 35×48 → 17×24
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.Conv2d(64, 64, 3, padding=1), nn.BatchNorm2d(64), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(0.1),

            # Block 3: 17×24 → 8×12
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.Conv2d(128, 128, 3, padding=1), nn.BatchNorm2d(128), nn.ReLU(inplace=True),
            nn.MaxPool2d(2, 2),
            nn.Dropout2d(0.2),

            # Block 4: 保持通道，使用 AdaptiveAvgPool 输出固定 4×6
            nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(inplace=True),
            nn.AdaptiveAvgPool2d((4, 6)),      # → 4H × 6W（保持宽高比约 1:1.37）
        )

        self.classifier = nn.Sequential(
            nn.Flatten(),                       # 256 × 4 × 6 = 6144
            nn.Linear(256 * 4 * 6, 512),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout),
            nn.Linear(512, 128),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout / 2),
            nn.Linear(128, num_classes),
        )

        self._init_weights()

    def _init_weights(self):
        for m in self.modules():
            if isinstance(m, nn.Conv2d):
                nn.init.kaiming_normal_(m.weight, mode="fan_out", nonlinearity="relu")
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.BatchNorm2d):
                nn.init.ones_(m.weight)
                nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Linear):
                nn.init.xavier_uniform_(m.weight)
                nn.init.zeros_(m.bias)

    def forward(self, x):
        x = self.features(x)
        return self.classifier(x)


# ─────────────────────────────────────────────
# 方案二：ResNet18 迁移学习（推荐，精度更高）
# ─────────────────────────────────────────────
class DigitResNet(nn.Module):
    """
    基于 ResNet18 的迁移学习模型，适配 70×96 小尺寸非正方形输入。

    关键改动：
      - 将 ResNet 第一层 conv1(7×7, stride=2) 替换为 3×3, stride=1，
        避免小图片在第一层就损失过多空间信息。
      - 去掉 maxpool（原 ResNet 连续两次下采样对 70px 高度过激进）。
      - 冻结策略：前 N 轮冻结 layer1/layer2，之后解冻全量微调。
    """

    def __init__(self, num_classes=10, freeze_layers=True, dropout=0.4):
        super().__init__()
        base = models.resnet18(weights=models.ResNet18_Weights.IMAGENET1K_V1)

        # ── 替换第一层，适配小尺寸 ──
        # 原: Conv2d(3, 64, kernel_size=7, stride=2, padding=3)
        # 改: Conv2d(3, 64, kernel_size=3, stride=1, padding=1)，减少首层下采样
        base.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
        nn.init.kaiming_normal_(base.conv1.weight, mode="fan_out", nonlinearity="relu")

        # 去掉 maxpool，避免 70px 高度连续两次 stride=2 损失过多细节
        base.maxpool = nn.Identity()

        if freeze_layers:
            # 冻结 layer1、layer2，仅微调后半部分和新 conv1
            for name, param in base.named_parameters():
                if any(name.startswith(p) for p in ["bn1", "layer1", "layer2"]):
                    param.requires_grad = False

        in_features = base.fc.in_features  # 512
        base.fc = nn.Sequential(
            nn.Dropout(dropout),
            nn.Linear(in_features, 256),
            nn.ReLU(inplace=True),
            nn.Dropout(dropout / 2),
            nn.Linear(256, num_classes),
        )
        self.model = base

    def forward(self, x):
        return self.model(x)

    def unfreeze_all(self):
        """在后期训练时解冻全部参数，进行全量微调"""
        for param in self.model.parameters():
            param.requires_grad = True
        print("已解冻所有层，进入全量微调阶段")


# ─────────────────────────────────────────────
# 工厂函数
# ─────────────────────────────────────────────
def build_model(model_type="resnet", num_classes=10, **kwargs):
    """
    Args:
        model_type:  "cnn" 或 "resnet"
        num_classes: 分类数，默认 10（0~9）
    """
    if model_type == "cnn":
        model = DigitCNN(num_classes=num_classes, **kwargs)
        print(f"[模型] DigitCNN（70×96 输入），参数量: {count_params(model):,}")
    elif model_type == "resnet":
        model = DigitResNet(num_classes=num_classes, **kwargs)
        print(f"[模型] DigitResNet18（70×96 输入，conv1已改造），"
              f"可训练参数: {count_trainable_params(model):,}")
    else:
        raise ValueError(f"未知模型类型: {model_type}")
    return model


def count_params(model):
    return sum(p.numel() for p in model.parameters())

def count_trainable_params(model):
    return sum(p.numel() for p in model.parameters() if p.requires_grad)
