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
    ANGLE_ROI_TOP_RATIO, ANGLE_ROI_BOTTOM_RATIO,
    ANGLE_ROI_LEFT_RATIO, ANGLE_ROI_RIGHT_RATIO,
)

# ─────────────────────────────────────────────
#  截取风速区域
# ─────────────────────────────────────────────

def capture_angle_roi(hwnd: int) -> Optional[np.ndarray]:
    """
    截取游戏左下角角度显示区域。
    区域为客户区宽高的固定比例，自动适配任意分辨率。
    """
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    win_w = right - left
    win_h = bottom - top

    x1 = int(win_w * ANGLE_ROI_LEFT_RATIO)
    x2 = int(win_w * ANGLE_ROI_RIGHT_RATIO)
    y1 = int(win_h * ANGLE_ROI_TOP_RATIO)
    y2 = int(win_h * ANGLE_ROI_BOTTOM_RATIO)
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