"""
core/capture.py
截图 + 视野矩形识别 + 圆点检测
——基于你原有的灰色蒙版识别逻辑扩展
"""

import cv2
import numpy as np
import win32gui
import win32con
import win32ui
import ctypes
from PIL import Image
from dataclasses import dataclass
from typing import Optional, Tuple, List

from config.settings import (
    WINDOW_TITLE_KEY, MINIMAP_CROP_WIDTH, MINIMAP_CROP_HEIGHT,
    MINIMAP_Y_OFFSET, GRAY_BRIGHT_MIN, GRAY_BRIGHT_MAX,
    GRAY_MAX_CHAN_DIFF, ADJUST_PIXEL, VIEWPORT_GAME_UNITS,
    CIRCLE_DP, CIRCLE_MIN_DIST, CIRCLE_PARAM1, CIRCLE_PARAM2,
    CIRCLE_MIN_RADIUS, CIRCLE_MAX_RADIUS,
    PLAYER_RING_DELTA_MIN, PLAYER_RING_DELTA_MAX,
)


@dataclass
class MinimapState:
    """一次小地图识别的完整结果"""
    # 视野矩形在小地图截图中的位置/尺寸（像素）
    viewport_x: int
    viewport_y: int
    viewport_w: int
    viewport_h: int

    # 比例：1 游戏单位 = scale_px 像素（基于矩形宽度）
    scale_px: float          # = viewport_w / VIEWPORT_GAME_UNITS

    # 玩家圆点在小地图截图中的像素坐标
    player_px: Optional[Tuple[float, float]]

    # 目标圆点列表（可能有多个）
    targets_px: List[Tuple[float, float]]

    # 换算后的距离（游戏单位）：相对玩家的 (dx, dy)
    # dy > 0 表示目标比玩家高（小地图Y轴向下 → 游戏Y轴取反）
    targets_game: List[Tuple[float, float]]


# ─────────────────────────────────────────────
#  窗口捕获
# ─────────────────────────────────────────────

def get_window_handle(keyword: str = WINDOW_TITLE_KEY) -> Optional[int]:
    """按标题关键字查找窗口句柄"""
    found = []
    def _cb(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and keyword in win32gui.GetWindowText(hwnd):
            found.append(hwnd)
        return True
    win32gui.EnumWindows(_cb, None)
    return found[0] if found else None


def capture_minimap(hwnd: int) -> Optional[np.ndarray]:
    """
    截取右上角小地图区域，返回 BGR numpy 数组。
    区域固定为：x = win_w - CROP_W, y = MINIMAP_Y_OFFSET
    """
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    win_w = right - left
    crop_x = win_w - MINIMAP_CROP_WIDTH

    hwnd_dc = win32gui.GetDC(hwnd)
    mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp     = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, MINIMAP_CROP_WIDTH, MINIMAP_CROP_HEIGHT)
    save_dc.SelectObject(bmp)

    ctypes.windll.gdi32.BitBlt(
        save_dc.GetSafeHdc(), 0, 0, MINIMAP_CROP_WIDTH, MINIMAP_CROP_HEIGHT,
        mfc_dc.GetSafeHdc(), crop_x, MINIMAP_Y_OFFSET, win32con.SRCCOPY
    )

    bmp_str = bmp.GetBitmapBits(True)
    img_pil = Image.frombuffer(
        'RGB', (MINIMAP_CROP_WIDTH, MINIMAP_CROP_HEIGHT),
        bmp_str, 'raw', 'BGRX', 0, 1
    )

    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    # 转为 OpenCV BGR 格式
    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


def capture_fullscreen(hwnd: int) -> Optional[np.ndarray]:
    """截取游戏完整客户区（用于覆盖层坐标映射）"""
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    w = right - left
    h = bottom - top

    hwnd_dc = win32gui.GetDC(hwnd)
    mfc_dc  = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bmp     = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(mfc_dc, w, h)
    save_dc.SelectObject(bmp)

    ctypes.windll.gdi32.BitBlt(
        save_dc.GetSafeHdc(), 0, 0, w, h,
        mfc_dc.GetSafeHdc(), 0, 0, win32con.SRCCOPY
    )

    bmp_str = bmp.GetBitmapBits(True)
    img_pil = Image.frombuffer('RGB', (w, h), bmp_str, 'raw', 'BGRX', 0, 1)

    win32gui.DeleteObject(bmp.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)

    return cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)


# ─────────────────────────────────────────────
#  视野矩形识别（你的核心算法，稍作封装）
# ─────────────────────────────────────────────

def _is_gray(r: int, g: int, b: int) -> bool:
    bright = (r + g + b) / 3
    if not (GRAY_BRIGHT_MIN <= bright <= GRAY_BRIGHT_MAX):
        return False
    return (max(r, g, b) - min(r, g, b)) <= GRAY_MAX_CHAN_DIFF


def detect_viewport_rect(minimap_bgr: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    """
    在小地图截图中检测视野矩形（灰色半透明蒙版）。
    返回 (x, y, w, h)，即矩形在截图中的位置和尺寸。
    None 表示未检测到。

    完全复用你原有的像素遍历 + 轮廓检测逻辑。
    """
    img_rgb = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2RGB)
    h, w = img_rgb.shape[:2]

    # 生成灰色像素的二值掩码
    binary = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            r, g, b = int(img_rgb[y, x, 0]), int(img_rgb[y, x, 1]), int(img_rgb[y, x, 2])
            if _is_gray(r, g, b):
                binary[y, x] = 255

    # 查找轮廓
    _, thresh = cv2.threshold(binary, 127, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None

    best_rect  = None
    best_score = 0

    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area < 500:
            continue
        epsilon = 0.02 * cv2.arcLength(cnt, True)
        approx  = cv2.approxPolyDP(cnt, epsilon, True)
        rx, ry, rw, rh = cv2.boundingRect(cnt)
        rect_area  = rw * rh
        fill_ratio = area / rect_area if rect_area > 0 else 0

        if len(approx) == 4 and fill_ratio > 0.6 and rect_area > 1000:
            score = area * fill_ratio
            if score > best_score:
                best_score = score
                best_rect  = (rx, ry, rw - ADJUST_PIXEL, rh - ADJUST_PIXEL)

    # 退而求其次：最大轮廓的外接矩形
    if best_rect is None:
        largest = max(contours, key=cv2.contourArea)
        rx, ry, rw, rh = cv2.boundingRect(largest)
        best_rect = (rx, ry, rw - ADJUST_PIXEL, rh - ADJUST_PIXEL)

    return best_rect


# ─────────────────────────────────────────────
#  圆点识别：玩家 vs 目标
# ─────────────────────────────────────────────

def detect_dots(minimap_bgr: np.ndarray) -> Tuple[Optional[Tuple], List[Tuple]]:
    """
    在小地图截图中检测所有圆点，区分玩家（有外环）和目标。

    策略：
    1. 对小地图做高斯模糊 + HoughCircles 检测所有圆
    2. 对每个圆，在稍大半径处检测是否还有同色圆弧 → 判断外环 → 玩家
    3. 其余为目标点

    返回：(player_center, [target_centers])
    坐标均为 (cx, cy) float，像素单位
    """
    gray = cv2.cvtColor(minimap_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 1)

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=CIRCLE_DP,
        minDist=CIRCLE_MIN_DIST,
        param1=CIRCLE_PARAM1,
        param2=CIRCLE_PARAM2,
        minRadius=CIRCLE_MIN_RADIUS,
        maxRadius=CIRCLE_MAX_RADIUS,
    )

    if circles is None:
        return None, []

    circles = np.round(circles[0]).astype(int)

    player_center = None
    player_score  = -1
    targets       = []

    for (cx, cy, r) in circles:
        # 检测外环：在 r + DELTA 处采样像素，看是否有明显圆弧
        ring_score = _measure_ring(minimap_bgr, cx, cy, r)
        if ring_score > player_score:
            player_score  = ring_score
            player_center = (float(cx), float(cy))

    # 将非玩家圆点归为目标
    for (cx, cy, r) in circles:
        if player_center and abs(cx - player_center[0]) < 2 and abs(cy - player_center[1]) < 2:
            continue
        targets.append((float(cx), float(cy)))

    return player_center, targets


def _measure_ring(img_bgr: np.ndarray, cx: int, cy: int, r: int) -> float:
    """
    在圆心 (cx,cy) 外侧 r+DELTA 处采样，计算与内圆的颜色相似度（外环强度）。
    返回值越高代表越像"有外环"的玩家圆点。
    """
    h, w = img_bgr.shape[:2]
    scores = []
    for delta in range(PLAYER_RING_DELTA_MIN, PLAYER_RING_DELTA_MAX + 1):
        outer_r = r + delta
        # 采样外环上8个点
        sample_pixels = []
        for angle_deg in range(0, 360, 45):
            rad = np.deg2rad(angle_deg)
            sx = int(cx + outer_r * np.cos(rad))
            sy = int(cy + outer_r * np.sin(rad))
            if 0 <= sx < w and 0 <= sy < h:
                sample_pixels.append(img_bgr[sy, sx].astype(float))

        if not sample_pixels:
            continue

        # 外环颜色均值
        outer_mean = np.mean(sample_pixels, axis=0)

        # 内圆中心颜色
        inner_color = img_bgr[cy, cx].astype(float)

        # 相似度：颜色接近且亮度够（排除黑色边缘）
        brightness = np.mean(outer_mean)
        color_diff = np.linalg.norm(outer_mean - inner_color)
        if brightness > 50:
            scores.append(1.0 / (1.0 + color_diff / 50.0))

    return max(scores) if scores else 0.0


# ─────────────────────────────────────────────
#  统一入口：一次识别返回完整状态
# ─────────────────────────────────────────────

def analyze_minimap(hwnd: int) -> Optional[MinimapState]:
    """
    完整的小地图分析：
    截图 → 检测视野矩形 → 算比例 → 检测圆点 → 换算游戏坐标
    """
    minimap = capture_minimap(hwnd)
    if minimap is None:
        return None

    # 1. 视野矩形 → 比例
    rect = detect_viewport_rect(minimap)
    if rect is None:
        print("[capture] 未检测到视野矩形")
        return None

    vx, vy, vw, vh = rect
    scale_px = vw / VIEWPORT_GAME_UNITS   # 1游戏单位 = scale_px 像素

    # 2. 圆点
    player_px, targets_px = detect_dots(minimap)

    # 3. 换算游戏坐标（相对玩家）
    targets_game = []
    if player_px and targets_px:
        px, py = player_px
        for tx, ty in targets_px:
            dx_game =  (tx - px) / scale_px          # 正 = 目标在右
            dy_game = -(ty - py) / scale_px          # 负号：屏幕Y向下，游戏Y向上
            targets_game.append((dx_game, dy_game))

    return MinimapState(
        viewport_x=vx, viewport_y=vy,
        viewport_w=vw, viewport_h=vh,
        scale_px=scale_px,
        player_px=player_px,
        targets_px=targets_px,
        targets_game=targets_game,
    )
