import os
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from PIL import Image
import numpy as np
from tqdm import tqdm

# ----------------------
# 1. 配置与字符集
# ----------------------
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
BATCH_SIZE = 32
EPOCHS = 10
LR = 0.001
DATA_DIR = "./dataset"

CHARSET = "0123456789."
CHAR2IDX = {c: i for i, c in enumerate(CHARSET)}
IDX2CHAR = {i: c for i, c in enumerate(CHARSET)}
NUM_CLASSES = len(CHARSET)


# ----------------------
# 2. 数据集定义
# ----------------------
class NumberDataset(Dataset):
    def __init__(self, data_dir, transform=None):
        self.data_dir = data_dir
        self.transform = transform
        self.image_paths = []
        self.labels = []

        # 加载所有图像路径和标签
        for root, _, files in os.walk(data_dir):
            for file in files:
                if file.endswith(".png"):
                    text = file.split("_")[-1].replace(".png", "")
                    self.image_paths.append(os.path.join(root, file))
                    self.labels.append(text)

    def __len__(self):
        return len(self.image_paths)

    def __getitem__(self, idx):
        img = Image.open(self.image_paths[idx]).convert("L")  # 灰度图
        if self.transform:
            img = self.transform(img)

        # 标签转换为字符索引
        label = [CHAR2IDX[c] for c in self.labels[idx]]
        return img, torch.tensor(label, dtype=torch.long)


# 数据预处理
transform = transforms.Compose([
    transforms.Resize((32, 128)),  # 高度32，宽度128
    transforms.ToTensor(),
    transforms.Normalize((0.5,), (0.5,))  # 归一化到[-1, 1]
])

# 加载数据集
dataset = NumberDataset(DATA_DIR, transform=transform)
dataloader = DataLoader(dataset, batch_size=BATCH_SIZE, shuffle=True, collate_fn=lambda x: x)


# ----------------------
# 3. 轻量级CRNN模型定义
# ----------------------
class LightCRNN(nn.Module):
    def __init__(self, num_classes):
        super().__init__()
        # CNN特征提取
        self.cnn = nn.Sequential(
            nn.Conv2d(1, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),  # [batch, 16, 16, 64]
            nn.Conv2d(16, 32, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),  # [batch, 32, 8, 32]
            nn.Conv2d(32, 64, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.MaxPool2d(2, 2),  # [batch, 64, 4, 16]
        )
        # RNN序列建模
        self.rnn = nn.GRU(
            input_size=64 * 4,
            hidden_size=64,
            num_layers=1,
            bidirectional=True,
            batch_first=True
        )
        # 分类层
        self.fc = nn.Linear(64 * 2, num_classes)

    def forward(self, x):
        # CNN特征提取
        x = self.cnn(x)  # [batch, 64, 4, 16]
        # 转换为RNN输入格式: [batch, seq_len, feature_dim]
        x = x.permute(0, 3, 1, 2)  # [batch, 16, 64, 4]
        x = x.flatten(2)  # [batch, 16, 256]
        # RNN建模
        x, _ = self.rnn(x)  # [batch, 16, 128]
        # 分类
        x = self.fc(x)  # [batch, 16, num_classes]
        return x.log_softmax(2)


# ----------------------
# 4. 训练准备
# ----------------------
model = LightCRNN(NUM_CLASSES).to(DEVICE)
criterion = nn.CTCLoss(blank=NUM_CLASSES)  # CTC损失，空白符索引为NUM_CLASSES
optimizer = optim.Adam(model.parameters(), lr=LR)


# ----------------------
# 5. 训练循环
# ----------------------
def train_epoch():
    model.train()
    total_loss = 0
    for batch in tqdm(dataloader, desc="Training"):
        # 整理batch数据
        images = torch.stack([item[0] for item in batch]).to(DEVICE)
        labels = [item[1] for item in batch]
        label_lengths = torch.tensor([len(label) for label in labels], dtype=torch.long)
        labels = torch.cat(labels).to(DEVICE)

        # 前向传播
        optimizer.zero_grad()
        outputs = model(images)  # [batch, seq_len, num_classes]
        input_lengths = torch.tensor([outputs.size(1)] * outputs.size(0), dtype=torch.long)

        # 计算CTC损失
        loss = criterion(outputs.permute(1, 0, 2), labels, input_lengths, label_lengths)

        # 反向传播
        loss.backward()
        optimizer.step()
        total_loss += loss.item()

    return total_loss / len(dataloader)


# 开始训练
for epoch in range(EPOCHS):
    loss = train_epoch()
    print(f"Epoch {epoch + 1}/{EPOCHS}, Loss: {loss:.4f}")
    # 保存模型
    torch.save(model.state_dict(), f"crnn_epoch_{epoch + 1}.pth")

print("训练完成！模型已保存。")