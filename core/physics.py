"""
core/physics.py
弹道物理引擎 + 参数标定 + 角度/力度求解器

弹道方程（完整版含风偏）：
  Δy = Δx·tan(θ) - g·Δx² / [2·(v0·P/100)²·cos²(θ)]
       + kw·w·Δx / (v0·P/100·cos(θ))

变量说明：
  θ  - 发射角度（弧度），仰角为正
  P  - 蓄力值 0~100
  v0 - 满蓄力初速度（游戏单位/s，需标定）
  g  - 游戏重力常数（需标定）
  kw - 风速系数（需标定）
  w  - 当前风速（-5~+5，正=向右）
  Δx - 水平距离（游戏单位，正=目标在右）
  Δy - 高差（游戏单位，正=目标比玩家高）
"""

import json
import math
import numpy as np
from typing import Optional, Tuple, List
from dataclasses import dataclass, asdict

from config.settings import (
    PHYSICS_V0, PHYSICS_G, PHYSICS_KW,
    SOLVER_THETA_MIN, SOLVER_THETA_MAX, SOLVER_THETA_STEP,
    SOLVER_POWER_MIN, SOLVER_POWER_MAX,
    CALIBRATION_FILE, MIN_CALIBRATION_SHOTS,
)


# ─────────────────────────────────────────────
#  物理参数（可被标定更新）
# ─────────────────────────────────────────────

@dataclass
class PhysicsParams:
    v0: float = PHYSICS_V0
    g:  float = PHYSICS_G
    kw: float = PHYSICS_KW

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PhysicsParams":
        return cls(**d)


# 全局参数实例（运行时可更新）
_params = PhysicsParams()


def get_params() -> PhysicsParams:
    return _params


def set_params(p: PhysicsParams):
    global _params
    _params = p


# ─────────────────────────────────────────────
#  弹道方程正向计算
# ─────────────────────────────────────────────

def predict_landing(
    theta_deg: float,
    power: float,
    wind: float,
    dx: float,
    params: Optional[PhysicsParams] = None,
) -> float:
    """
    给定发射角度、蓄力、风速、水平距离，
    预测弹丸落点的垂直坐标（相对玩家，正=上方）。

    theta_deg: 发射角（度），仰角为正
    power:     蓄力 0~100
    wind:      风速 -5~+5
    dx:        水平距离（游戏单位，正=目标在右）

    注意：如果目标在左侧（dx < 0），需要翻转角度和风向再调用。
    """
    if params is None:
        params = _params

    theta = math.radians(theta_deg)
    v = params.v0 * power / 100.0

    if abs(v) < 1e-6 or abs(math.cos(theta)) < 1e-6:
        return float('nan')

    cos_t = math.cos(theta)
    tan_t = math.tan(theta)

    # 斜抛项
    parabola = dx * tan_t - params.g * dx**2 / (2 * v**2 * cos_t**2)
    # 风偏项（横向风速使弹丸偏移）
    wind_effect = params.kw * wind * abs(dx) / (v * cos_t)

    return parabola + wind_effect


def trajectory_points(
    theta_deg: float,
    power: float,
    wind: float,
    max_range: float,
    n_points: int = 60,
    params: Optional[PhysicsParams] = None,
) -> List[Tuple[float, float]]:
    """
    生成弹道轨迹点列表，用于覆盖层绘制。
    返回 [(dx, dy), ...] 游戏坐标序列。
    """
    if params is None:
        params = _params

    pts = []
    for i in range(n_points + 1):
        dx = max_range * i / n_points
        dy = predict_landing(theta_deg, power, wind, dx, params)
        if math.isnan(dy):
            break
        pts.append((dx, dy))
        if dy < -50:   # 落地后停止绘制
            break
    return pts


# ─────────────────────────────────────────────
#  求解器：给定目标位置 + 风速 → 最优(θ, P)
# ─────────────────────────────────────────────

@dataclass
class SolveResult:
    theta_deg: float    # 建议发射角（度）
    power: float        # 建议蓄力（0~100）
    wind: float         # 本次使用的风速
    dx: float           # 水平距离（游戏单位）
    dy: float           # 高差（游戏单位，正=目标高）
    error: float        # 预测误差（游戏单位，越小越准）
    feasible: bool      # 是否找到可行解


def solve_aim(
    dx: float,
    dy: float,
    wind: float,
    prefer_low_angle: bool = True,
    params: Optional[PhysicsParams] = None,
) -> SolveResult:
    """
    核心求解器：枚举角度，二分法求蓄力。

    dx: 目标水平距离（游戏单位，正=右）
    dy: 目标高差（游戏单位，正=目标比玩家高）
    wind: 风速
    prefer_low_angle: True=优先低仰角（平射），False=优先高仰角（抛物线）
    """
    if params is None:
        params = _params

    # 如果目标在左侧，翻转坐标系（发射方向取反，风向也取反）
    flip = dx < 0
    if flip:
        dx   = -dx
        wind = -wind

    if dx < 0.5:
        # 目标几乎在同一位置，用最小力度垂直射击
        return SolveResult(
            theta_deg=85, power=10, wind=wind,
            dx=dx, dy=dy, error=999, feasible=False
        )

    best = None
    best_error = float('inf')

    theta_range = np.arange(SOLVER_THETA_MIN, SOLVER_THETA_MAX, SOLVER_THETA_STEP)
    if not prefer_low_angle:
        theta_range = theta_range[::-1]

    for theta_deg in theta_range:
        # 对当前角度，用二分法在 [POWER_MIN, POWER_MAX] 中找到使落点匹配 dy 的蓄力
        p = _bisect_power(theta_deg, wind, dx, dy, params)
        if p is None:
            continue

        # 验证误差
        predicted_dy = predict_landing(theta_deg, p, wind, dx, params)
        err = abs(predicted_dy - dy)

        if err < best_error:
            best_error = err
            best = (theta_deg, p)

        # 足够精确就提前退出
        if err < 0.1:
            break

    if best is None:
        return SolveResult(
            theta_deg=45, power=50, wind=wind,
            dx=dx, dy=dy, error=999, feasible=False
        )

    theta_deg, power = best
    # 如果翻转了方向，角度不变（发射角仍是仰角），玩家自行调整朝向
    return SolveResult(
        theta_deg=round(theta_deg, 1),
        power=round(power, 1),
        wind=wind if not flip else -wind,
        dx=-dx if flip else dx,
        dy=dy,
        error=round(best_error, 3),
        feasible=best_error < 2.0,
    )


def _bisect_power(
    theta_deg: float,
    wind: float,
    dx: float,
    dy: float,
    params: PhysicsParams,
    iterations: int = 30,
) -> Optional[float]:
    """
    二分法：对固定 θ，找到使 predict_landing(...) ≈ dy 的蓄力 P。
    如果在 [POWER_MIN, POWER_MAX] 范围内无解，返回 None。
    """
    lo, hi = float(SOLVER_POWER_MIN), float(SOLVER_POWER_MAX)

    f_lo = predict_landing(theta_deg, lo, wind, dx, params) - dy
    f_hi = predict_landing(theta_deg, hi, wind, dx, params) - dy

    if math.isnan(f_lo) or math.isnan(f_hi):
        return None

    # 函数需要在两端变号才能二分
    if f_lo * f_hi > 0:
        # 找最接近的端点
        err_lo = abs(f_lo)
        err_hi = abs(f_hi)
        # 如果误差可接受就返回端点值
        if min(err_lo, err_hi) < 3.0:
            return lo if err_lo < err_hi else hi
        return None

    for _ in range(iterations):
        mid = (lo + hi) / 2
        f_mid = predict_landing(theta_deg, mid, wind, dx, params) - dy
        if math.isnan(f_mid):
            return None
        if abs(f_mid) < 0.01:
            return mid
        if f_lo * f_mid < 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid

    return (lo + hi) / 2


# ─────────────────────────────────────────────
#  标定系统：历史数据拟合物理参数
# ─────────────────────────────────────────────

@dataclass
class ShotRecord:
    """一次发射的完整记录"""
    theta_deg: float   # 实际使用的角度
    power: float       # 实际蓄力
    wind: float        # 风速
    dx_actual: float   # 实际水平落点（游戏单位）
    dy_actual: float   # 实际垂直落点（游戏单位）


_shot_history: List[ShotRecord] = []


def record_shot(record: ShotRecord):
    """记录一次发射数据"""
    _shot_history.append(record)
    _save_calibration()
    if len(_shot_history) >= MIN_CALIBRATION_SHOTS:
        _fit_params()


def _fit_params():
    """用最小二乘法拟合 v0, g, kw"""
    try:
        from scipy.optimize import curve_fit
    except ImportError:
        print("[physics] scipy 未安装，跳过自动标定")
        return

    if len(_shot_history) < MIN_CALIBRATION_SHOTS:
        return

    def model(X, v0, g, kw):
        results = []
        for theta_deg, power, wind, dx in zip(*X):
            theta = math.radians(theta_deg)
            v = v0 * power / 100.0
            if abs(v) < 1e-6 or abs(math.cos(theta)) < 1e-6:
                results.append(float('nan'))
                continue
            cos_t = math.cos(theta)
            tan_t = math.tan(theta)
            dy = (dx * tan_t
                  - g * dx**2 / (2 * v**2 * cos_t**2)
                  + kw * wind * abs(dx) / (v * cos_t))
            results.append(dy)
        return np.array(results)

    thetas  = [r.theta_deg  for r in _shot_history]
    powers  = [r.power      for r in _shot_history]
    winds   = [r.wind       for r in _shot_history]
    dxs     = [r.dx_actual  for r in _shot_history]
    dys     = [r.dy_actual  for r in _shot_history]

    X = (thetas, powers, winds, dxs)
    y = np.array(dys)

    try:
        global _params
        popt, _ = curve_fit(
            model, X, y,
            p0=[_params.v0, _params.g, _params.kw],
            maxfev=5000,
            bounds=([1, 0.1, 0], [200, 100, 5]),
        )

        _params = PhysicsParams(v0=popt[0], g=popt[1], kw=popt[2])
        print(f"[physics] 标定完成: v0={popt[0]:.2f}, g={popt[1]:.2f}, kw={popt[2]:.3f}")
        _save_calibration()
    except Exception as e:
        print(f"[physics] 标定失败: {e}")


def _save_calibration():
    data = {
        "params": _params.to_dict(),
        "history": [asdict(r) for r in _shot_history],
    }
    try:
        with open(CALIBRATION_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[physics] 保存标定数据失败: {e}")


def load_calibration():
    """启动时加载历史标定数据"""
    global _params, _shot_history
    if not __import__('os').path.exists(CALIBRATION_FILE):
        return
    try:
        with open(CALIBRATION_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if 'params' in data:
            _params = PhysicsParams.from_dict(data['params'])
        if 'history' in data:
            _shot_history = [ShotRecord(**r) for r in data['history']]
        print(f"[physics] 加载标定: v0={_params.v0:.2f}, g={_params.g:.2f}, kw={_params.kw:.3f}, 历史{len(_shot_history)}条")
    except Exception as e:
        print(f"[physics] 加载标定数据失败: {e}")
