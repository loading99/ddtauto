"""
tools/debug.py
调试工具：单独测试各模块，帮助调参。

用法（在项目根目录运行）：
  python tools/debug.py minimap   # 测试小地图识别（按S触发）
  python tools/debug.py wind      # 测试风速识别
  python tools/debug.py physics   # 测试物理计算（手动输入参数）
  python tools/debug.py calibrate # 查看当前标定参数
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import cv2
import numpy as np
import keyboard
import time


def debug_minimap():
    """测试小地图识别，可视化结果"""
    from core.capture import get_window_handle, capture_minimap, detect_viewport_rect, detect_dots

    print("按 S 键截图并识别小地图...")
    keyboard.wait('s')

    hwnd = get_window_handle()
    if not hwnd:
        print("未找到窗口")
        return

    minimap = capture_minimap(hwnd)
    if minimap is None:
        print("截图失败")
        return

    cv2.imwrite("debug_minimap_raw.png", minimap)
    print("原始小地图已保存: debug_minimap_raw.png")

    # 检测视野矩形
    rect = detect_viewport_rect(minimap)
    vis = minimap.copy()

    if rect:
        x, y, w, h = rect
        scale = w / 10.0
        print(f"\n✅ 视野矩形: ({x},{y}) {w}×{h}px")
        print(f"   比例: 1游戏单位 = {scale:.2f}px")
        cv2.rectangle(vis, (x, y), (x+w, y+h), (0, 0, 255), 2)
        cv2.putText(vis, f"{w}x{h} scale={scale:.1f}", (x, y-5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
    else:
        print("❌ 未检测到视野矩形")

    # 检测圆点
    player, targets = detect_dots(minimap)
    if player:
        cx, cy = int(player[0]), int(player[1])
        cv2.circle(vis, (cx, cy), 8, (0, 255, 255), 2)
        cv2.putText(vis, "P", (cx+10, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
        print(f"\n✅ 玩家圆点: ({cx}, {cy})")
    else:
        print("\n❌ 未检测到玩家圆点")

    for i, (tx, ty) in enumerate(targets):
        cv2.circle(vis, (int(tx), int(ty)), 6, (0, 255, 0), 2)
        cv2.putText(vis, f"T{i}", (int(tx)+8, int(ty)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        if player and rect:
            dx = (tx - player[0]) / (rect[2] / 10.0)
            dy = -(ty - player[1]) / (rect[3] / 10.0)   # Y翻转
            print(f"✅ 目标{i}: ({int(tx)},{int(ty)}) → 游戏坐标 Δx={dx:.2f}, Δy={dy:.2f}")

    cv2.imwrite("debug_minimap_result.png", vis)
    print("\n识别结果已保存: debug_minimap_result.png")

    # 放大显示
    big = cv2.resize(vis, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
    cv2.imshow("Minimap Debug (按Q关闭)", big)
    cv2.waitKey(0)
    cv2.destroyAllWindows()


def debug_wind():
    """测试风速识别"""
    from core.capture import get_window_handle
    from core.wind import capture_wind_roi, detect_wind

    hwnd = get_window_handle()
    if not hwnd:
        print("未找到窗口")
        return

    print("连续识别风速，按 Q 停止, 按S 保存...")
    os.makedirs('wind', exist_ok=True)
    while True:
        print("正在保存")
        timestamp = int(time.time())
        roi = capture_wind_roi(hwnd)
        if roi is not None:
            cv2.imwrite(f'wind/wind_{timestamp}.png', roi)
        time.sleep(2)
        if keyboard.is_pressed('q'):
            break


def debug_physics():
    """测试物理计算"""
    from core.physics import solve_aim, predict_landing, PhysicsParams

    print("\n=== 物理计算调试 ===")
    print("输入目标参数（回车使用默认）:")
    dx   = float(input("  水平距离 Δx (游戏单位) [默认 15.0]: ") or "15.0")
    dy   = float(input("  高差 Δy (游戏单位, 正=目标高) [默认 0.0]: ") or "0.0")
    wind = float(input("  风速 w (-5~5) [默认 0]: ") or "0")

    result = solve_aim(dx, dy, wind)
    print(f"\n  建议角度:  {result.theta_deg}°")
    print(f"  建议蓄力:  {result.power:.0f} / 100")
    print(f"  预测误差:  {result.error:.3f} 游戏单位")
    print(f"  状态:      {'✓ 可行解' if result.feasible else '✗ 估算解'}")

    # 验证：用求解结果反推落点
    predicted = predict_landing(result.theta_deg, result.power, wind, abs(dx))
    print(f"\n  验证: 预测落点 Δy={predicted:.3f} (目标 Δy={dy:.3f})")
    print(f"        误差 = {abs(predicted - dy):.3f} 游戏单位")


def debug_calibrate():
    """显示当前标定参数"""
    from core.physics import load_calibration, get_params, _shot_history

    load_calibration()
    params = get_params()
    print(f"\n=== 当前物理参数 ===")
    print(f"  v0 (最大初速度): {params.v0:.3f}")
    print(f"  g  (重力系数):   {params.g:.3f}")
    print(f"  kw (风速系数):   {params.kw:.4f}")
    print(f"\n  历史发射记录: {len(_shot_history)} 条")

    if _shot_history:
        print("\n  最近5条记录:")
        for r in _shot_history[-5:]:
            print(f"    θ={r.theta_deg}° P={r.power:.0f} w={r.wind:+.0f} "
                  f"→ ({r.dx_actual:.1f}, {r.dy_actual:.1f})")

def debug_angle():
    """测试风速识别"""
    from core.capture import get_window_handle
    from core.angle import capture_angle_roi

    hwnd = get_window_handle()
    if not hwnd:
        print("未找到窗口")
        return

    print("连续识别角度，按 Q 停止, 按S 保存...")
    os.makedirs('angle', exist_ok=True)
    while True:
        print("正在保存")
        timestamp = int(time.time())
        roi = capture_angle_roi(hwnd)
        if roi is not None:
            cv2.imwrite(f'angle/angle_{timestamp}.png', roi)
        time.sleep(2)
        if keyboard.is_pressed('q'):
            break


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'minimap'
    {
        'minimap':   debug_minimap,
        'wind':      debug_wind,
        'physics':   debug_physics,
        'calibrate': debug_calibrate,
        'angle': debug_angle,
    }.get(cmd, debug_minimap)()
