# Assignment + Routing 快速优化版

本目录是独立的 Assignment + Routing V2。原始 baseline 和 Reposition 版本均未修改；本版本默认关闭重定位，集中优化准点率，同时控制搜索规模。

当前默认实验数据为 `../merchant_data_full_with_zones.csv`（17,867个唯一订单）；旧数据入口仍可通过 `--input` 显式指定。

该文件的经纬度已经是小数度数；读取器会自动兼容这种格式和旧数据的百万倍整数格式。`zone_id` 会保留在源数据中，但当前无重定位的 Assignment/Routing 不使用分区参与决策。

## 默认参数

```text
fleet_size = 800（当前full_zones数据；小数据为独立120人骑手池）
speed = 20 km/h
distance_metric = rectilinear
max_active_orders = 8
candidate_riders = 8
insertion_position_limit = 3
ready_time_buffer = 0
dispatch_processing = 1分钟
pickup_service = 1分钟
delivery_service = 2分钟
late_order_weight = 100
enable_on_time_protection = true
enable_high_risk_expansion = true
high_risk_candidate_riders = 12
high_risk_insertion_position_limit = 4
enable_route_optimization = true
route_optimization_min_active_orders = 3
route_optimization_max_passes = 2
route_optimization_position_limit = 4
reposition_policy = none
```

## 优化方法

### 混合候选骑手

普通订单仍只详细评估8名骑手，但候选不再全部由地理距离决定：

```text
4名距离商家最近
2名当前活动订单数最少
2名预计完整取餐时间最早
```

去重后使用预计取餐时间和距离补齐。每名骑手缓存预计路线释放时间与位置，路线变化时才更新，因此不需要为每个订单完整模拟全部骑手。

### 截止时间导向插入

普通订单每名骑手最多保留3个取餐位置和3个送餐位置：

```text
局部新增距离最小位置
最早合法位置
按照订单截止时间对齐的位置
```

最多仍为 `3 × 3 = 9` 条路线。高风险扩展时增加路线尾部位置，最多为 `4 × 4 = 16` 条。

### 准时保护

若候选方案中存在不增加迟到订单数的路线，则只在这些路线中比较：

```text
新增距离 + 5 × 新增迟到分钟 + late_order_weight × 新增迟到订单数
```

这使准点率优先于少量距离节省，也是迟到权重100～500得到相同路线的原因。

### 高风险动态扩展

若普通8名骑手、3×3插入得到的最佳方案仍预计迟到，则仅对该订单扩大为：

```text
12名骑手
4个取餐位置 × 4个送餐位置
```

普通订单不扩大搜索。

### 骑手内部路径优化

同一分钟的贪心分配结束后，仅对至少持有3单、且当前路线预计存在迟到的骑手进行局部修复。每次最多两轮：

```text
未取餐订单：同时移除取餐点和送餐点，再成对重新插入
已取餐订单：只重新安排送餐点
正在行驶的下一站：冻结，不允许修改
```

每轮最多为移动节点保留4个较有希望的位置，并始终保证取餐先于送餐。候选路线不得增加迟到订单数，且只有以下路线目标严格下降才接受：

```text
剩余距离 + 5 × 预计总迟到分钟 + 100 × 预计迟到订单数
```

可使用 `--disable-route-optimization` 关闭，作为无路径优化对照。

### 完整取餐时间

正式取餐时间定义为：

```text
assignment_to_pickup_min
= simulated_pickup_time - assignment_time
```

它包括接单后的处理、前序路线、到店行驶、等餐和取餐服务时间。`pickup_leg_min` 仍只表示取餐前最后一段行驶时间。

## 权重实验结果

当前默认数据使用权重100、800名骑手和20 km/h，并开启骑手内部路径优化。结果为：17,754单完成、113单拒绝、99.37%完单率、69.70%总体准点率、总超时339,198.85分钟、总距离41,512.39 km，运行约100～107秒。结果保存在 `outputs/full_zones_800_route_optimized`。

| 800骑手对照 | 无路径优化 | 有路径优化 | 变化 |
|---|---:|---:|---:|
| 总体准点率 | 67.57% | 69.70% | +2.13个百分点 |
| 准时订单 | 12,073 | 12,454 | +381 |
| 拒绝订单 | 114 | 113 | -1 |
| 总超时分钟 | 418,858.70 | 339,198.85 | -79,659.85 |
| 总距离km | 42,331.86 | 41,512.39 | -819.46 |
| 加权总目标 | 2,818,625.36 | 2,380,506.64 | -438,118.73 |
| 运行时间 | 75.1秒 | 107.0秒 | +31.9秒 |

迟到订单权重100、200、300、400、500均已测试。由于准时保护先筛除新增迟到订单的方案，五档权重在两组数据中选择了完全相同的路线。

| 数据 | 权重 | 完单率 | 准点率 | 总超时分钟 | 总距离km | 运行时间 |
|---|---:|---:|---:|---:|---:|---:|
| 2,247单 / 120骑手 | 100～500 | 100% | 81.93% | 17,354.86 | 5,909.78 | 约4.0秒 |
| 22,408单 / 1,300骑手 | 100～500 | 100% | 88.91% | 56,920.65 | 50,999.00 | 约36.6秒 |

两组均为0拒单、0未完成订单。大数据准点率比历史值88.19%高0.72个百分点。

## 对照结果

| 数据 | 原始15km/h、Q=15 | 仅改20km/h、Q=8、buffer=0 | 完整优化版 |
|---|---:|---:|---:|
| 小数据准点率 | 64.26% | 77.17% | 81.93% |
| 大数据准点率 | 63.55% | 75.65% | 88.91% |

这表明提升不仅来自速度和容量参数。混合候选、截止时间插入、准时保护和高风险扩展在小数据额外提高4.76个百分点，在大数据额外提高13.26个百分点。

## 运行

运行当前默认数据 `merchant_data_full_with_zones.csv`：

```powershell
python run_baseline.py
```

运行小数据：

```powershell
python run_baseline.py --input ..\2000.xlsx --sheet-name sampled_data --courier-input ..\courier_pools\couriers_120.csv --fleet-size 120 --output-dir outputs\small_latest
```

运行当前默认数据的权重实验（默认数据选择为 `full_zones`）：

```powershell
python run_late_weight_sweep.py
```

旧的小/大数据权重对照仍可分别使用 `--dataset small`、`--dataset large`，或用 `--dataset both` 同时运行。

权重汇总表写入：

```text
outputs/late_weight_sweep/weight_sweep_results.csv
```

## 输出

- `order_results.csv`：逐单Assignment、取餐、送达、迟到和决策分数；新增完整取餐时间字段。
- `courier_summary.csv`：逐骑手订单数、距离、忙碌时间和最终位置。
- `metrics.csv` / `metrics.json`：核心比例、时间、距离、目标值和运行配置。
- `summary_results.csv`：总距离、完单率、准点率和总超时。
- `invalid_orders.csv`：未进入仿真的异常或重复订单。
- `run_config.json`：可复现实验参数。
- `reposition_events.csv`：为保持输出结构兼容而保留；默认无重定位时只有表头。

当前版本不计算或输出公平性指标。
