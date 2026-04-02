"""
main.py
弹弹堂自瞄准系统 - 主程序入口

快捷键：
  F1  - 立即识别并计算（单次触发）
  F2  - 开启/关闭连续自动识别
  F3  - 记录上次发射落点（用于标定）
  F4  - 保存风速模板（在已知风速时按下）
  ESC - 退出
"""

import time
import keyboard
import threading
import sys
import os

# 确保可以引用本项目包
sys.path.insert(0, os.path.dirname(__file__))

from core.capture  import get_window_handle, analyze_minimap
from core.wind     import detect_wind, save_wind_template
from core.physics  import solve_aim, load_calibration, record_shot, ShotRecord
from overlay.window import OverlayWindow, CoordMapper, get_game_window_rect
from config.settings import VIEWPORT_GAME_UNITS


# ─────────────────────────────────────────────
#  全局状态
# ─────────────────────────────────────────────

_hwnd       = None
_overlay    = OverlayWindow()
_auto_mode  = False
_last_result = None
_last_mapper = None
_last_wind   = 0


def _get_hwnd():
    global _hwnd
    if _hwnd is None or not _hwnd:
        _hwnd = get_window_handle()
        if _hwnd:
            print(f"[main] 找到游戏窗口: hwnd={_hwnd}")
        else:
            print("[main] ⚠ 未找到游戏窗口，请确认游戏已启动")
    return _hwnd


# ─────────────────────────────────────────────
#  核心识别与计算流程
# ─────────────────────────────────────────────

def run_once():
    """执行一次完整的识别+计算+覆盖层更新"""
    global _last_result, _last_mapper, _last_wind

    hwnd = _get_hwnd()
    if not hwnd:
        return

    # 1. 分析小地图（视野矩形 + 圆点）
    state = analyze_minimap(hwnd)
    if state is None:
        print("[main] 小地图识别失败")
        _overlay.update(None, None)
        return

    print(f"[main] 视野矩形: {state.viewport_w}×{state.viewport_h}px | "
          f"比例: 1单位={state.scale_px:.2f}px")

    if state.player_px is None:
        print("[main] ⚠ 未检测到玩家圆点")
        _overlay.update(None, None)
        return

    if not state.targets_game:
        print("[main] ⚠ 未检测到目标圆点")
        _overlay.update(None, None)
        return

    # 取最近目标（最小距离）
    target_game = min(
        state.targets_game,
        key=lambda t: t[0]**2 + t[1]**2
    )
    dx, dy = target_game
    print(f"[main] 目标游戏坐标: Δx={dx:.1f}, Δy={dy:.1f}")

    # 2. 识别风速
    wind = detect_wind(hwnd)
    print(f"[main] 风速: {wind:+d}")

    # 3. 计算瞄准参数
    result = solve_aim(dx, dy, wind)
    print(f"[main] 计算结果: 角度={result.theta_deg}°  蓄力={result.power:.0f}  "
          f"误差={result.error:.2f}  {'✓' if result.feasible else '✗'}")

    # 4. 构建坐标映射（游戏坐标 → 屏幕坐标）
    # 获取游戏窗口在屏幕上的位置
    screen_x, screen_y, win_w, win_h = get_game_window_rect(hwnd)
    # 玩家在主画面中的位置（近似：玩家在主画面中间偏左下方）
    # 由于玩家总是在当前视口中，其在小地图视野矩形内的相对位置可以换算
    # 粗略假设：玩家在主画面中心（后续可从主画面图像识别精确位置）
    if state.player_px:
        # 玩家圆点在小地图截图中的相对位置（相对视野矩形）
        px_in_vp = (state.player_px[0] - state.viewport_x) / state.viewport_w  # 0~1
        py_in_vp = (state.player_px[1] - state.viewport_y) / state.viewport_h  # 0~1
        # 换算到主画面屏幕坐标
        player_sx = screen_x + px_in_vp * win_w
        player_sy = screen_y + py_in_vp * win_h
    else:
        player_sx = screen_x + win_w * 0.5
        player_sy = screen_y + win_h * 0.7

    mapper = CoordMapper(
        player_screen_x=player_sx,
        player_screen_y=player_sy,
        game_win_x=screen_x,
        game_win_y=screen_y,
        game_win_w=win_w,
        game_win_h=win_h,
        viewport_game_w=float(VIEWPORT_GAME_UNITS),
    )

    _last_result = result
    _last_mapper = mapper
    _last_wind   = wind

    # 5. 更新覆盖层
    _overlay.update(result, mapper, wind)


# ─────────────────────────────────────────────
#  快捷键处理
# ─────────────────────────────────────────────

def _on_f1():
    print("\n[F1] 单次识别触发")
    threading.Thread(target=run_once, daemon=True).start()


def _on_f2():
    global _auto_mode
    _auto_mode = not _auto_mode
    print(f"\n[F2] 自动模式: {'开启' if _auto_mode else '关闭'}")


def _on_f3():
    """记录落点用于标定（需要玩家手动输入落点坐标）"""
    if _last_result is None:
        print("\n[F3] 无上次计算结果，无法记录")
        return
    print("\n[F3] 请输入实际落点坐标（相对玩家，游戏单位）:")
    try:
        dx = float(input("  实际 Δx = "))
        dy = float(input("  实际 Δy = "))
        record = ShotRecord(
            theta_deg=_last_result.theta_deg,
            power=_last_result.power,
            wind=_last_wind,
            dx_actual=dx,
            dy_actual=dy,
        )
        record_shot(record)
        print(f"[F3] 已记录落点 ({dx:.1f}, {dy:.1f})")
    except ValueError:
        print("[F3] 输入无效")


def _on_f4():
    """保存当前风速模板"""
    hwnd = _get_hwnd()
    if not hwnd:
        return
    try:
        wind = int(input("\n[F4] 当前风速是多少 (-5~5)? "))
        save_wind_template(hwnd, wind)
    except ValueError:
        print("[F4] 输入无效")


def _on_esc():
    global _running
    print("\n[ESC] 退出")
    _running = False
    _overlay.stop()


_running = True


def _auto_loop():
    """自动模式：每0.5秒识别一次"""
    while _running:
        if _auto_mode:
            run_once()
        time.sleep(0.5)


# ─────────────────────────────────────────────
#  主入口
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  弹弹堂自瞄准系统 v1.0")
    print("=" * 60)
    print("  F1  - 单次识别计算")
    print("  F2  - 开/关自动模式（每0.5s）")
    print("  F3  - 记录落点（标定用）")
    print("  F4  - 保存风速模板")
    print("  ESC - 退出")
    print("=" * 60)

    # 加载历史标定数据
    load_calibration()

    # 启动覆盖层
    _overlay.start()
    time.sleep(0.3)   # 等待 tkinter 初始化

    # 注册快捷键
    keyboard.add_hotkey('f1',  _on_f1)
    keyboard.add_hotkey('f2',  _on_f2)
    keyboard.add_hotkey('f3',  _on_f3)
    keyboard.add_hotkey('ctrl+f4',  _on_f4)
    keyboard.add_hotkey('esc', _on_esc)

    # 自动模式后台线程
    auto_thread = threading.Thread(target=_auto_loop, daemon=True)
    auto_thread.start()

    print("\n等待按键...")
    while _running:
        time.sleep(0.1)

    print("已退出")


if __name__ == '__main__':
    main()
