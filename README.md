# Rapid Food Delivery Dispatch

外卖骑手快速分配、路径规划与重定位研究系统。

An event-driven research simulator for fast courier assignment, pickup-and-delivery routing, and demand-aware repositioning in on-demand food delivery.

本项目研究订单动态到达时如何快速选择骑手、插入取送餐节点、修复预计迟到的路线，以及根据已观测需求调动空闲或即将完成服务的骑手。当前实现是可复现实验系统，尚未接入真实外卖平台、实时导航或生产调度服务。

## 核心方法

- **事件驱动调度**：订单发布、骑手上线和到站事件推进仿真；取餐必须早于送餐，正在前往的下一站冻结。
- **混合候选骑手**：先宽筛 256 人，再选 4 名顺路骑手、2 名低负载骑手和 2 名预计取餐最早的骑手。
- **有限插入搜索**：普通订单检查最多 3×3 个取送餐位置；预计迟到时扩展至 12 名骑手和 4×4 个位置。
- **准时保护与局部路径修复**：优先保留不增加迟到订单数的候选路线，对拥挤且预计迟到的路线进行保持取送顺序的局部优化。
- **Gamma-Poisson 重定位实验**：默认使用历史已发布订单预测分区需求，考虑服务容量、迟到风险、移动成本和调动限制；支持服务完成后的重定位计划。

系统目标为 `总距离 km + 1000 × 未服务订单数 + 5 × 总迟到分钟 + 100 × 迟到订单数`。默认速度为 20 km/h，使用近似曼哈顿距离，每名骑手最多持有 8 个未完成订单。

## 版本与目录

| 路径 | 内容 |
|---|---|
| `code/` | 工作总结中的最终分配与路径规划基准，默认关闭重定位 |
| `repositioning/` | 原工作目录中较新的 Gamma-Poisson 重定位实验及成对比较脚本 |
| `fast_baseline/` | 2026-08-20 保留的快速基准，供历史对照 |
| `data_global/` | 数据说明和原始使用限制；实际数据需在本地放置 |
| `reference_results/` | 基准结果、重定位与顺路候选实验的汇总指标和参数 |
| `docs/` | 项目方法、结果说明、整理记录和原始工作总结 |

三个实现分别保留自己的 `baseline.py`，以便独立比较。不要在同一 Python 进程中混合导入它们；测试分别运行。

## 安装

推荐 64 位 Python 3.10 或 3.11。

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r code/requirements.txt
```

Windows PowerShell 的激活命令为 `.\.venv\Scripts\Activate.ps1`。可选绘图脚本还需要 `matplotlib`：`python -m pip install matplotlib`。

## 数据准备

将合法取得的两份项目数据放入 `data_global/`：

```text
merchant_data_2200_with_zones_global.csv
merchant_data_full_with_zones_global.csv
```

它们分别包含 2,200 和 17,867 个唯一订单，小数据是完整数据的精确子集。原始订单、顾客坐标、骑手记录和逐单输出未上传。数据使用限制及所需字段见 [数据说明](data_global/README.md)。不要将这些文件提交到 GitHub。

## 运行与验证

在仓库根目录分别运行已有测试：

```bash
python -m unittest discover -s code/tests -v
python -m unittest discover -s repositioning/tests -v
python -m unittest discover -s fast_baseline/tests -v
```

复现最终基准的三组实验并核对保留指标：

```bash
python code/run_reproduction_experiments.py
python code/verify_reproduction.py
```

先运行小规模基准：

```bash
python code/run_reproduction_experiments.py --case small_120
```

运行小规模重定位成对比较：

```bash
python repositioning/run_reposition_comparison.py --input data_global/merchant_data_2200_with_zones_global.csv --fleet-size 120 --output-dir repositioning/outputs/small_comparison
```

比较 800、900、1000、1100 名骑手时的重定位效果：

```bash
python repositioning/run_fleet_reposition_comparison.py
```

`repositioning/run_baseline.py` 默认启用 `gamma_poisson` 和 `causal_gamma_poisson`。严格对照使用 `--reposition-policy none`。`perfect_horizon_benchmark` 使用未来需求作为理想信息基准，不能当作在线预测效果。

历史快速基准可显式指定数据运行：

```bash
python fast_baseline/run_baseline.py --input data_global/merchant_data_full_with_zones_global.csv --fleet-size 800
```

## 已有结果与边界

工作总结保留的无重定位基准结果如下，运行时间来自历史设备：

| 订单数 / 骑手数 | 完单率 | 总体准点率 | 拒单 | 历史运行时间 |
|---|---:|---:|---:|---:|
| 2,200 / 120 | 100.00% | 84.91% | 0 | 9.70 秒 |
| 2,200 / 100 | 99.68% | 71.45% | 7 | 14.84 秒 |
| 17,867 / 800 | 99.98% | 77.68% | 3 | 181.15 秒 |

最新保留的因果预测与服务后重定位对照中，800 人时准点率略降，900 和 1000 人时准点率不变且总目标增加，1100 人时没有发生调动。**当前证据不支持重定位已稳定改善配送效果。** 详细表格和不同实验阶段的解释见 [结果说明](docs/RESULTS.md)。

这里的“快速”指通过限制候选和搜索规模降低计算成本；历史整段仿真耗时不是生产系统单次响应延迟，也不是实时服务等级保证。固定速度、近似路网、历史重建骑手池及贪心决策都限制了结果的外推范围。

## 资料与使用说明

- [算法与重定位流程](docs/METHOD.md)
- [实验结果和验证记录](docs/RESULTS.md)
- [原始复现与扩展指南](docs/original/Assignment_Routing实验复现与扩展指南.docx)
- [整理范围及来源](docs/REPOSITORY_PREPARATION.md)

代码未自动附加新的开源许可证；原始数据的限制独立适用。第三方论文、原始数据全集、浏览器缓存、虚拟环境和重复逐单输出未纳入仓库。
