# ============================================================
#  弹弹堂自瞄准系统 - 全局配置
# ============================================================

# ---------- 窗口识别 ----------
WINDOW_TITLE_KEY = "4399-520"

# ---------- 小地图截图区域（右上角） ----------
# 从窗口右上角截取的像素尺寸，根据你的实际游戏分辨率微调
MINIMAP_CROP_WIDTH  = 232
MINIMAP_CROP_HEIGHT = 120
MINIMAP_Y_OFFSET    = 50   # 距窗口顶部的偏移

# ---------- 视野矩形识别（灰色半透明蒙版） ----------
# 灰色像素的亮度范围和最大色差
GRAY_BRIGHT_MIN     = 120
GRAY_BRIGHT_MAX     = 180
GRAY_MAX_CHAN_DIFF  = 22
ADJUST_PIXEL        = 1    # 矩形尺寸修正偏移（你原代码中的微调）

# 1个视野矩形宽度 = 10 游戏距离单位（核心比例常数）
VIEWPORT_GAME_UNITS = 10

# ---------- 玩家圆点识别 ----------
# 玩家圆点有同心外环，目标点没有，用双圆检测区分
# HoughCircles 参数（可根据实际效果调整）
CIRCLE_DP           = 1
CIRCLE_MIN_DIST     = 8
CIRCLE_PARAM1       = 50
CIRCLE_PARAM2       = 12
CIRCLE_MIN_RADIUS   = 3
CIRCLE_MAX_RADIUS   = 12

# 玩家圆点外环检测：外环半径比内圆大多少像素
PLAYER_RING_DELTA_MIN = 3
PLAYER_RING_DELTA_MAX = 10

# ---------- 风速识别区域（顶部中间） ----------
# 相对游戏窗口的比例坐标（适配任意分辨率）
WIND_ROI_LEFT_RATIO   = 0.38
WIND_ROI_RIGHT_RATIO  = 0.62
WIND_ROI_TOP_RATIO    = 0.0382
WIND_ROI_BOTTOM_RATIO = 0.1184

# ---------- 物理参数（需要标定，初始估算值） ----------
# 初速度最大值（满蓄力100时），单位：游戏距离/帧 或相对单位
# 实际值通过历史记录拟合得出，这里是保守初始值
PHYSICS_V0    = 28.0    # 满蓄力最大初速度（游戏单位/s，需标定）
PHYSICS_G     = 9.8     # 重力加速度（游戏单位/s²，需标定）
PHYSICS_KW    = 0.3     # 风速影响系数（需标定）

# 蓄力与初速度的关系：v = V0 * (power / 100)
# power 范围：0 ~ 100

# ---------- 求解器参数 ----------
SOLVER_THETA_MIN    = 5    # 枚举角度最小值（度）
SOLVER_THETA_MAX    = 85   # 枚举角度最大值（度）
SOLVER_THETA_STEP   = 0.5  # 枚举步长（度）
SOLVER_POWER_MIN    = 10   # 蓄力最小值
SOLVER_POWER_MAX    = 100  # 蓄力最大值

# ---------- 覆盖层样式 ----------
OVERLAY_FPS         = 20
OVERLAY_BG_COLOR    = (0, 0, 0, 160)      # RGBA，半透明黑色信息框
OVERLAY_TARGET_COLOR= (255, 50, 50, 255)  # 目标X标记颜色
OVERLAY_TRAJ_COLOR  = (255, 200, 0, 200)  # 弹道预测线颜色
OVERLAY_TEXT_COLOR  = (255, 255, 255, 255)

# ---------- 标定数据存储 ----------
CALIBRATION_FILE    = "calibration_data.json"
MIN_CALIBRATION_SHOTS = 5   # 至少这么多条数据才开始拟合
