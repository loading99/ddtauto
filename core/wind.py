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
import os
import re
import win32gui
import win32con
import win32ui
import ctypes
from PIL import Image
from typing import Optional

from config.settings import (
    WIND_ROI_LEFT_RATIO, WIND_ROI_RIGHT_RATIO,
    WIND_ROI_TOP_RATIO, WIND_ROI_BOTTOM_RATIO,
)

TEMPLATE_DIR = "wind_templates"   # 存放 wind_-5.png ... wind_5.png


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
#  策略 A：模板匹配
# ─────────────────────────────────────────────

_templates: dict = {}   # {wind_value: gray_template_img}

def _load_templates():
    """加载模板图片，-5 到 +5 共11个值"""
    global _templates
    if not os.path.isdir(TEMPLATE_DIR):
        return False
    for v in range(-5, 6):
        fname = os.path.join(TEMPLATE_DIR, f"wind_{v}.png")
        if os.path.exists(fname):
            tmpl = cv2.imread(fname, cv2.IMREAD_GRAYSCALE)
            if tmpl is not None:
                _templates[v] = tmpl
    return len(_templates) > 0


def _detect_by_template(roi_bgr: np.ndarray) -> Optional[int]:
    """模板匹配风速，返回 -5~5 的整数，失败返回 None"""
    if not _templates:
        if not _load_templates():
            return None

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    best_val  = -1.0
    best_wind = None

    for wind_val, tmpl in _templates.items():
        # 如果模板比ROI大则跳过
        if tmpl.shape[0] > gray.shape[0] or tmpl.shape[1] > gray.shape[1]:
            continue
        res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, _ = cv2.minMaxLoc(res)
        if max_val > best_val:
            best_val  = max_val
            best_wind = wind_val

    if best_val < 0.6:   # 置信度阈值
        return None
    return best_wind


# ─────────────────────────────────────────────
#  策略 B：OCR（fallback）
# ─────────────────────────────────────────────

def _detect_by_ocr(roi_bgr: np.ndarray) -> Optional[int]:
    """
    用 Tesseract 识别风速数字。
    要求安装: pip install pytesseract  +  系统安装 Tesseract。
    """
    try:
        import pytesseract
    except ImportError:
        return None

    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    # 放大2x + 二值化，提升OCR准确率
    scaled = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    _, binary = cv2.threshold(scaled, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    cfg = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789+-'
    text = pytesseract.image_to_string(binary, config=cfg).strip()

    # 提取数字（含负号）
    match = re.search(r'[+-]?\d+', text)
    if match:
        val = int(match.group())
        if -5 <= val <= 5:
            return val
    return None


# ─────────────────────────────────────────────
#  策略 C：像素计数法（不依赖任何外部库的最后防线）
# ─────────────────────────────────────────────

def _detect_by_pixel_heuristic(roi_bgr: np.ndarray) -> Optional[int]:
    """
    简单启发式：弹弹堂的风速箭头向右偏 = 正风，向左 = 负风。
    通过检测顶部风速区域中橙色/黄色箭头像素的水平重心判断方向和强度。
    注意：这是粗略估计，误差约 ±1。
    """
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    # 橙色范围（箭头颜色）
    lower = np.array([10, 100, 150])
    upper = np.array([30, 255, 255])
    mask  = cv2.inRange(hsv, lower, upper)

    pixels = cv2.findNonZero(mask)
    if pixels is None or len(pixels) < 5:
        return 0   # 默认无风

    xs = pixels[:, 0, 0]
    cx = float(np.mean(xs))
    img_cx = roi_bgr.shape[1] / 2.0

    # 水平偏移映射到 -5~5
    offset_ratio = (cx - img_cx) / (img_cx)   # -1 ~ +1
    wind = round(offset_ratio * 5)
    return max(-5, min(5, wind))


# ─────────────────────────────────────────────
#  统一入口
# ─────────────────────────────────────────────

def detect_wind(hwnd: int) -> int:
    """
    识别当前风速，返回 -5 ~ +5 的整数（正 = 向右）。
    自动按优先级尝试三种策略。
    """
    roi = capture_wind_roi(hwnd)
    if roi is None:
        return 0

    # 优先级：模板 > OCR > 像素
    result = _detect_by_template(roi)
    if result is not None:
        return result

    result = _detect_by_ocr(roi)
    if result is not None:
        return result

    result = _detect_by_pixel_heuristic(roi)
    return result if result is not None else 0


def save_wind_template(hwnd: int, wind_value: int):
    """
    工具函数：在已知风速为 wind_value 时截图保存为模板。
    使用方法：在游戏中看到风速为 N 时调用此函数。
    """
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    roi = capture_wind_roi(hwnd)
    if roi is not None:
        path = os.path.join(TEMPLATE_DIR, f"wind_{wind_value}.png")
        cv2.imwrite(path, roi)
        print(f"[wind] 模板已保存: {path}")
