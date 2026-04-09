"""
core/wind.py
风速识别：从游戏顶部中间区域读取 -5 ~ +5 的风速值。

两种策略（可切换）：
A. 模板匹配：预先截图保存各风速值的数字图像作为模板
B. Tesseract OCR：直接识别数字（需要安装 tesseract）

默认使用 A（更稳定，不依赖外部安装）。
如果模板目录不存在则自动回退到 B。
"""

import cv2
import numpy as np
import win32gui
import win32con
import win32ui
import ctypes
from typing import Optional
import torch
from PIL import Image
from torchvision import transforms

# 假设方向模型与数字模型的定义文件在同一目录下，可按实际路径调整
from models.multi_task_net import WindNet  # 方向识别模型
from models.model import build_model  # 数字识别模型构建函数
from config.settings import (
    WIND_ROI_LEFT_RATIO, WIND_ROI_RIGHT_RATIO,
    WIND_ROI_TOP_RATIO, WIND_ROI_BOTTOM_RATIO,
)

# ─────────────────────────────────────────────
#  截取风速区域
# ─────────────────────────────────────────────

def capture_wind_roi(hwnd: int) -> Optional[np.ndarray]:
    """
    截取游戏顶部中间风速显示区域。
    区域为客户区宽高的固定比例，自动适配任意分辨率。
    """
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    win_w = right - left
    win_h = bottom - top

    x1 = int(win_w * WIND_ROI_LEFT_RATIO)
    x2 = int(win_w * WIND_ROI_RIGHT_RATIO)
    y1 = int(win_h * WIND_ROI_TOP_RATIO)
    y2 = int(win_h * WIND_ROI_BOTTOM_RATIO)
    roi_w = x2 - x1
    roi_h = y2 - y1

    hwnd_dc = win32gui.GetDC(hwnd)
    mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp     = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, roi_w, roi_h)
    save_dc.SelectObject(bmp)

    ctypes.windll.gdi32.BitBlt(
        save_dc.GetSafeHdc(), 0, 0, roi_w, roi_h,
        mfc_dc.GetSafeHdc(), x1, y1, win32con.SRCCOPY
    )

    bmp_str = bmp.GetBitmapBits(True)
    img_pil = Image.frombuffer('RGB', (roi_w, roi_h), bmp_str, 'raw', 'BGRX', 0, 1)

    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

# ─────────────────────────────────────────────
#  统一入口
# ─────────────────────────────────────────────


class WindReader:
    """
    风力图读取器：
        - 识别箭头方向（左/右）
        - 识别风速（0.0 ~ 5.0）
    """

    def __init__(self,
                 direction_model_path='best_direction_model.pth',
                 digit_model_path='checkpoints/best_model.pth',
                 device=None):
        """
        初始化并加载模型

        Args:
            direction_model_path: 方向识别模型权重文件路径
            digit_model_path:     数字识别模型权重文件路径
            device:               运行设备，None 则自动选择
        """
        if device is None:
            self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        else:
            self.device = torch.device(device)

        print(f"[WindReader] 使用设备: {self.device}")

        # ---------- 加载方向识别模型 ----------
        print(f"[WindReader] 加载方向模型: {direction_model_path}")
        self.dir_model = WindNet().to(self.device)
        checkpoint_dir = torch.load(direction_model_path, map_location=self.device)
        self.dir_model.load_state_dict(checkpoint_dir)  # 假设直接保存 state_dict
        self.dir_model.eval()

        # 方向模型预处理 (与训练一致)
        self.dir_transform = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
        ])

        # ---------- 加载数字识别模型 ----------
        print(f"[WindReader] 加载数字模型: {digit_model_path}")
        ckpt = torch.load(digit_model_path, map_location=self.device)
        cfg = ckpt.get("config", {})
        self.digit_img_size = cfg.get("img_size", 64)
        model_type = cfg.get("model_type", "resnet")
        num_classes = cfg.get("num_classes", 10)

        self.digit_model = build_model(model_type, num_classes=num_classes)
        self.digit_model.load_state_dict(ckpt["model_state"])
        self.digit_model = self.digit_model.to(self.device)
        self.digit_model.eval()

        # 数字模型预处理
        self.digit_transform = transforms.Compose([
            transforms.Resize((self.digit_img_size, self.digit_img_size)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406],
                                 std=[0.229, 0.224, 0.225]),
        ])

        val_acc = ckpt.get("val_acc", "N/A")
        if isinstance(val_acc, float):
            print(f"[WindReader] 数字模型验证准确率: {val_acc * 100:.2f}%")
        print("[WindReader] 模型加载完成\n")

    def _load_image(self, image_input):
        """将输入统一转换为 RGB PIL Image"""
        if isinstance(image_input, str):
            img = Image.open(image_input).convert('RGB')
        elif isinstance(image_input, Image.Image):
            img = image_input.convert('RGB')
        else:
            # 假设为 numpy 数组
            from PIL import Image as PILImage
            import numpy as np
            if isinstance(image_input, np.ndarray):
                img = PILImage.fromarray(image_input).convert('RGB')
            else:
                raise TypeError("不支持的图像输入类型，支持：路径字符串、PIL.Image、numpy数组")
        return img

    @torch.no_grad()
    def _predict_direction(self, img_pil):
        """预测箭头方向，返回 ('+', 'right') 或 ('-', 'left')"""
        x = self.dir_transform(img_pil).unsqueeze(0).to(self.device)
        dir_logits, _ = self.dir_model(x)  # 模型返回两个输出，我们只需第一个
        direction_idx = dir_logits.argmax(dim=1).item()
        if direction_idx == 1:
            return '+', 'right'
        else:
            return '-', 'left'

    @torch.no_grad()
    def _predict_digit(self, img_pil):
        """识别单个数字图像，返回预测数字 (int)"""
        x = self.digit_transform(img_pil).unsqueeze(0).to(self.device)
        logits = self.digit_model(x)
        pred = logits.argmax(dim=1).item()
        return pred

    def predict(self, image_input):
        """
        对整张风力图进行识别

        Args:
            image_input: 图片路径 或 PIL.Image 对象

        Returns:
            dict: {
                "direction": "+" 或 "-",
                "tag": "right" 或 "left",
                "speed": float (0.0 ~ 5.0)
            }
        """
        img = self._load_image(image_input)
        width, height = img.size

        # 确保宽度至少为 86 (方向图) 和 48+38 (风速图)
        # 若不符合，根据实际需求可调整或报错，此处简单断言
        # assert width >= 86, f"图像宽度不足，至少需要 86 像素，当前 {width}"

        # 1. 方向识别：使用整张图（或约定区域，原脚本用整张 86x35）
        #    若输入图尺寸不同，需确认是否仍能正常识别；此处保持与原训练一致，假定输入就是 86x35
        direction_sign, direction_tag = self._predict_direction(img)

        # 2. 风速识别：从 x=48 处切分为左右两部分
        #    左半部分（整数部分）: 0 到 48 宽
        #    右半部分（小数部分）: 48 到 width
        left_part = img.crop((0, 0, 48, height))  # 整数位
        right_part = img.crop((48, 0, width, height))  # 小数位

        int_digit = self._predict_digit(left_part)
        frac_digit = self._predict_digit(right_part)

        speed = float(f"{int_digit}.{frac_digit}")

        return {
            "direction": direction_sign,
            "tag": direction_tag,
            "speed": speed
        }


reader = WindReader(
    direction_model_path='best_direction_model.pth',
    digit_model_path='checkpoints/best_model.pth'
)
def detect_wind(hwnd: int):
    """
    识别当前风速，返回 -5 ~ +5 的整数（正 = 向右）。
    自动按优先级尝试三种策略。
    """
    roi = capture_wind_roi(hwnd)
    return reader.predict(roi)


# ──────────────────────────────────────────────
# 使用示例
# ──────────────────────────────────────────────
if __name__ == '__main__':
    # 初始化读取器（请根据实际模型路径修改）
    reader = WindReader(
        direction_model_path='best_direction_model.pth',
        digit_model_path='checkpoints/best_model.pth'
    )

    # 单张图片预测
    test_image = r'E:\project\dandan_aim\tools\test\wind_1775667351.png'
    result = reader.predict(test_image)
    print("识别结果:", result)
