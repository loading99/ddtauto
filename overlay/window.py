"""
overlay/window.py
透明覆盖层窗口：在游戏画面上方显示目标标记、弹道预测线和建议参数。

使用 tkinter（Python内置，零依赖）实现透明点击穿透窗口：
- WS_EX_LAYERED + WS_EX_TRANSPARENT = 鼠标事件穿透（点不到）
- 始终在最顶层（topmost）
- Canvas 上绘制 X 标记、弧线、文字信息框
"""

import tkinter as tk
import math
import threading
import time
import win32gui
import win32con
import ctypes
from typing import Optional, List, Tuple

from config.settings import OVERLAY_FPS
from core.physics import SolveResult, trajectory_points, get_params


# ─────────────────────────────────────────────
#  坐标系转换：游戏坐标 → 屏幕像素
# ─────────────────────────────────────────────

class CoordMapper:
    """
    把游戏坐标（游戏单位，相对玩家）映射到屏幕像素坐标。

    需要知道：
    - 玩家在游戏主画面中的屏幕像素坐标（player_screen_x, player_screen_y）
    - 游戏画面的像素/游戏单位比例（scale_px）
      注意：这个 scale_px 是主画面的，不是小地图的
      主画面 scale = 小地图 scale × (主画面宽 / 小地图显示的全图宽)
      但由于主画面展示的是10个单位宽度的视口，
      主画面像素/游戏单位 = 主画面宽 / 10（精确值）
    """

    def __init__(
        self,
        player_screen_x: float,
        player_screen_y: float,
        game_win_x: int,       # 游戏窗口左上角屏幕坐标
        game_win_y: int,
        game_win_w: int,       # 游戏客户区宽度（像素）
        game_win_h: int,       # 游戏客户区高度（像素）
        viewport_game_w: float = 10.0,  # 视口宽度对应的游戏单位（固定=10）
    ):
        self.px    = player_screen_x
        self.py    = player_screen_y
        self.win_x = game_win_x
        self.win_y = game_win_y
        self.win_w = game_win_w
        self.win_h = game_win_h
        # 主画面每像素对应游戏单位（主画面宽 = 10游戏单位）
        self.screen_scale = game_win_w / viewport_game_w  # px/游戏单位

    def game_to_screen(self, dx_game: float, dy_game: float) -> Tuple[int, int]:
        """
        相对玩家的游戏坐标 (dx, dy) → 屏幕绝对像素坐标
        dy_game 正 = 目标比玩家高 → 屏幕 Y 减小（向上）
        """
        sx = int(self.px + dx_game * self.screen_scale)
        sy = int(self.py - dy_game * self.screen_scale)   # Y轴翻转
        return sx, sy

    def trajectory_to_screen(self, pts: List[Tuple[float, float]]) -> List[Tuple[int, int]]:
        return [self.game_to_screen(dx, dy) for dx, dy in pts]


# ─────────────────────────────────────────────
#  覆盖层窗口
# ─────────────────────────────────────────────

class OverlayWindow:
    """
    全屏透明覆盖层。

    使用方法：
        overlay = OverlayWindow()
        overlay.start()                          # 非阻塞，后台线程运行
        overlay.update(result, mapper, wind)     # 主循环中调用更新
        overlay.stop()
    """

    def __init__(self):
        self._root: Optional[tk.Tk] = None
        self._canvas: Optional[tk.Canvas] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # 待绘制数据
        self._solve_result: Optional[SolveResult] = None
        self._mapper: Optional[CoordMapper] = None
        self._wind: int = 0
        self._dirty = False

    # ── 公开接口 ──────────────────────────────

    def start(self):
        """在后台线程启动 tkinter 主循环"""
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._root:
            self._root.quit()

    def update(
        self,
        result: Optional[SolveResult],
        mapper: Optional[CoordMapper],
        wind: int = 0,
    ):
        """主线程调用，更新要绘制的数据（线程安全）"""
        with self._lock:
            self._solve_result = result
            self._mapper       = mapper
            self._wind         = wind
            self._dirty        = True

    # ── 内部实现 ──────────────────────────────

    def _run(self):
        self._root = tk.Tk()
        root = self._root

        # 获取屏幕尺寸
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()

        root.geometry(f"{sw}x{sh}+0+0")
        root.overrideredirect(True)           # 无边框无标题栏
        root.wm_attributes('-topmost', True)  # 始终在最顶层
        root.wm_attributes('-transparentcolor', 'black')  # 黑色背景完全透明
        root.configure(bg='black')

        # Canvas 黑色背景（透明区域）
        self._canvas = tk.Canvas(
            root, width=sw, height=sh,
            bg='black', highlightthickness=0
        )
        self._canvas.pack()

        # 设置点击穿透（Windows API）
        self._set_click_through(root)

        # 定时刷新
        interval_ms = int(1000 / OVERLAY_FPS)
        root.after(interval_ms, self._refresh_loop)
        root.mainloop()

    def _set_click_through(self, root: tk.Tk):
        """设置窗口鼠标事件穿透（WS_EX_TRANSPARENT）"""
        try:
            hwnd = int(root.frame(), 16)
            style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
            style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
            win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, style)
        except Exception as e:
            print(f"[overlay] 设置穿透失败（非致命）: {e}")

    def _refresh_loop(self):
        if not self._running:
            return
        with self._lock:
            if self._dirty:
                self._redraw()
                self._dirty = False
        interval_ms = int(1000 / OVERLAY_FPS)
        self._root.after(interval_ms, self._refresh_loop)

    def _redraw(self):
        c = self._canvas
        c.delete('all')   # 清空

        result = self._solve_result
        mapper = self._mapper

        if result is None or mapper is None:
            self._draw_status("⏳ 等待识别...")
            return

        # 1. 绘制目标X标记（屏幕坐标）
        target_screen = mapper.game_to_screen(result.dx, result.dy)
        self._draw_x(c, target_screen[0], target_screen[1])

        # 2. 绘制弹道预测弧线
        if result.feasible:
            pts_game = trajectory_points(
                result.theta_deg, result.power, self._wind,
                max_range=abs(result.dx) * 1.1,
                params=get_params(),
            )
            pts_screen = mapper.trajectory_to_screen(pts_game)
            if result.dx < 0:
                # 目标在左，轨迹水平翻转
                pts_screen = [
                    (2 * int(mapper.px) - x, y) for x, y in pts_screen
                ]
            if len(pts_screen) >= 2:
                self._draw_arc(c, pts_screen)

        # 3. 信息面板（左上角）
        self._draw_info_panel(c, result, self._wind)

    def _draw_x(self, c: tk.Canvas, sx: int, sy: int, size: int = 14):
        """绘制红色X标记"""
        color = '#FF3232'
        w = 2
        c.create_line(sx-size, sy-size, sx+size, sy+size, fill=color, width=w, tags='aim')
        c.create_line(sx+size, sy-size, sx-size, sy+size, fill=color, width=w, tags='aim')
        # 外圈
        c.create_oval(sx-size-4, sy-size-4, sx+size+4, sy+size+4,
                      outline=color, width=1, tags='aim')
        c.create_text(sx, sy+size+16, text="目标", fill=color,
                      font=('Microsoft YaHei', 10, 'bold'), tags='aim')

    def _draw_arc(self, c: tk.Canvas, pts: List[Tuple[int, int]]):
        """绘制弹道弧线（折线段连接）"""
        color = '#FFC800'
        for i in range(len(pts) - 1):
            x1, y1 = pts[i]
            x2, y2 = pts[i+1]
            c.create_line(x1, y1, x2, y2, fill=color, width=2,
                          dash=(6, 3), tags='traj')

    def _draw_info_panel(self, c: tk.Canvas, result: SolveResult, wind: int):
        """左上角半透明信息面板"""
        pad = 12
        x, y = 20, 20
        bw, bh = 240, 130

        # 半透明背景（用矩形模拟，stipple实现半透明效果）
        c.create_rectangle(
            x, y, x+bw, y+bh,
            fill='#001830', outline='#3399FF',
            width=1, stipple='gray50', tags='panel'
        )

        status_color = '#44FF88' if result.feasible else '#FF6644'
        status_text  = '✓ 可行解' if result.feasible else '✗ 估算解'

        lines = [
            (f"Δx: {result.dx:+.1f}  Δy: {result.dy:+.1f}  风: {wind:+d}", '#AACCFF'),
            ("", ''),
            (f"建议角度:  {result.theta_deg}°",        '#FFFFFF'),
            (f"建议蓄力:  {result.power:.0f} / 100",   '#FFD700'),
            (f"预测误差:  {result.error:.2f} 单位",    '#AAAAAA'),
            (f"状态:  {status_text}",                   status_color),
        ]

        ty = y + pad + 8
        c.create_text(x + pad, ty, text="🎯 弹弹堂自瞄", anchor='w',
                      fill='#66CCFF', font=('Microsoft YaHei', 11, 'bold'), tags='panel')
        ty += 22
        c.create_line(x+pad, ty, x+bw-pad, ty, fill='#3399FF', width=1, tags='panel')
        ty += 6

        for text, color in lines:
            if text:
                c.create_text(x + pad, ty, text=text, anchor='w',
                              fill=color, font=('Microsoft YaHei', 10), tags='panel')
            ty += 18

    def _draw_status(self, msg: str):
        """无数据时显示状态提示"""
        sw = self._root.winfo_screenwidth()
        self._canvas.create_text(
            sw // 2, 30, text=msg,
            fill='#888888', font=('Microsoft YaHei', 11), tags='status'
        )


# ─────────────────────────────────────────────
#  辅助：获取游戏窗口屏幕位置
# ─────────────────────────────────────────────

def get_game_window_rect(hwnd: int) -> Tuple[int, int, int, int]:
    """
    获取游戏窗口客户区在屏幕上的绝对坐标。
    返回 (screen_x, screen_y, client_w, client_h)
    """
    # 客户区左上角 → 屏幕坐标
    pt = ctypes.wintypes.POINT(0, 0)
    ctypes.windll.user32.ClientToScreen(hwnd, ctypes.byref(pt))
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    return pt.x, pt.y, right - left, bottom - top
