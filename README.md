# 弹弹堂自瞄准系统

## 项目结构

```
dandan_aim/
├── main.py                  # 主程序入口（直接运行这个）
├── requirements.txt
├── calibration_data.json    # 自动生成，物理参数标定数据
├── config/
│   └── settings.py          # 所有可调参数集中在这里
├── core/
│   ├── capture.py           # 截图 + 视野矩形识别 + 圆点检测
│   ├── wind.py              # 风速识别（三种策略）
│   └── physics.py           # 弹道物理计算 + 求解器 + 标定
├── overlay/
│   └── window.py            # 透明覆盖层窗口
├── tools/
│   └── debug.py             # 调试工具
└── wind_templates/          # 手动截图保存的风速模板（可选）
```

## 安装

```bash
pip install -r requirements.txt
```

需要以**管理员权限**运行（keyboard 库需要）。

## 快速开始

```bash
cd dandan_aim
python main.py
```

快捷键：
| 按键 | 功能 |
|------|------|
| F1   | 单次识别并计算 |
| F2   | 开/关自动模式（每0.5s识别一次） |
| F3   | 记录落点（用于标定物理参数） |
| F4   | 保存风速模板截图 |
| ESC  | 退出 |

## 核心原理

### 距离换算
```
视野矩形宽度（像素） = 10 游戏距离单位
比例 K = viewport_w / 10
玩家→目标 像素差 / K = 游戏距离
```

### 弹道方程
```
Δy = Δx·tan(θ) - g·Δx² / [2·(v0·P/100)²·cos²(θ)]
     + kw·w·Δx / (v0·P/100·cos(θ))
```

### 求解方法
枚举角度θ（5°~85°，步长0.5°），对每个θ用二分法求使落点匹配目标高差的蓄力P。

## 调试与调参

### 第一步：验证小地图识别
```bash
python tools/debug.py minimap
```
游戏中按 S，查看 `debug_minimap_result.png`：
- 红色矩形 = 识别到的视野矩形 ✓
- 青色圆圈 = 玩家位置（P）✓
- 绿色圆圈 = 目标位置（T0, T1...）✓

### 第二步：验证风速识别
```bash
python tools/debug.py wind
```
观察输出的风速值是否与游戏界面一致。

若不准：保存风速模板（在游戏中按 F4，输入当前风速），收集全部11个值（-5 到 +5）后模板匹配会很稳定。

### 第三步：标定物理参数（重要！）
初始 v0/g/kw 是估算值，真实值需要标定：

1. 打几局，每次发射后按 F3 记录实际落点
2. 积累 5 条以上后系统自动拟合参数
3. 越多数据越准，推荐 20~50 条

```bash
python tools/debug.py calibrate  # 查看当前参数
```

### 调整 config/settings.py 中的参数

| 参数 | 说明 | 调整依据 |
|------|------|---------|
| `MINIMAP_CROP_WIDTH/HEIGHT` | 小地图截图尺寸 | 根据你的游戏分辨率 |
| `GRAY_BRIGHT_MIN/MAX` | 灰色矩形亮度范围 | 若矩形识别失败可微调 |
| `CIRCLE_PARAM2` | 圆点检测灵敏度 | 越小越灵敏，可能误检 |
| `PHYSICS_V0/G/KW` | 物理初始估算值 | 标定后自动更新 |
| `SOLVER_THETA_STEP` | 角度搜索步长 | 越小越精确但更慢 |

## 常见问题

**Q: 视野矩形识别不到**
调整 `GRAY_BRIGHT_MIN/MAX` 和 `GRAY_MAX_CHAN_DIFF`，或增大 `MINIMAP_CROP_WIDTH/HEIGHT`

**Q: 圆点检测混乱（玩家和目标判断错误）**
调整 `CIRCLE_PARAM2`（降低避免误检），或 `PLAYER_RING_DELTA_MIN/MAX`

**Q: 蓄力/角度明显不对**
先用 `tools/debug.py physics` 手动测试物理计算，确认参数方向；再积累更多落点数据触发标定

**Q: 覆盖层遮住游戏**
覆盖层已设置鼠标穿透，你仍然可以正常操作游戏，覆盖层仅显示不拦截输入
