import torch.nn as nn
from torchvision.models import efficientnet_b0, EfficientNet_B0_Weights

class WindNet(nn.Module):
    def __init__(self, freeze_layers=4):
        super().__init__()
        backbone = efficientnet_b0(weights=EfficientNet_B0_Weights.IMAGENET1K_V1)

        # 冻结前 N 层
        layers = list(backbone.features.children())
        for i, layer in enumerate(layers):
            if i < freeze_layers:
                for p in layer.parameters():
                    p.requires_grad = False

        self.features = backbone.features
        self.pool = nn.AdaptiveAvgPool2d(1)

        feat_dim = 1280  # EfficientNet-B0 输出通道数

        # 方向分类头: 2 类 (left=0, right=1)
        self.dir_head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(feat_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 2)
        )

        # 风速回归头: 输出 [0,1]，乘以 4.9 还原
        self.speed_head = nn.Sequential(
            nn.Dropout(0.3),
            nn.Linear(feat_dim, 256),
            nn.ReLU(),
            nn.Linear(256, 1),
            nn.Sigmoid()
        )

    def forward(self, x):
        feat = self.pool(self.features(x)).flatten(1)
        dir_logits = self.dir_head(feat)       # [B, 2]
        speed = self.speed_head(feat).squeeze(1)  # [B]
        return dir_logits, speed