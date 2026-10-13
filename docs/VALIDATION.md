# 本地验证记录

验证日期：2026-10-13。实际验证环境为 Python 3.12.14、NumPy 2.3.5、pandas 2.2.3 和 openpyxl 3.1.5。原工作总结推荐 Python 3.10 或 3.11，本次额外确认这套 3.12 环境也通过了所列检查。所有命令在整理后的仓库根目录执行，原始下载目录未被修改。

## 已有单元测试

| 目录 | 测试数量 | 结果 |
|---|---:|---|
| `code/tests` | 11 | 全部通过 |
| `repositioning/tests` | 12 | 全部通过 |
| `fast_baseline/tests` | 10 | 全部通过 |

## 最终基准复现

执行 `python code/run_reproduction_experiments.py` 和 `python code/verify_reproduction.py`。`small_120`、`small_100`、`full_800` 均为 PASS，关键整数指标相同，浮点指标在绝对误差 1e-6 内一致。

本次整段仿真耗时分别约为 5.91、8.94 和 112.68 秒；耗时不纳入一致性校验，也不代表线上单次调度延迟。

## 重定位冒烟验证

运行 `repositioning/run_reposition_comparison.py`，使用 2,200 单、120 名骑手及默认因果 Gamma-Poisson 配置。无重定位与有重定位两组均完成全部订单，无拒单，准点率均为 84.9091%。有重定位版本执行 10 次移动，重定位距离 10.3330 km，服务距离减少 1.3720 km，净总距离和加权目标均增加 8.9610。

本次检查确认命令行入口、数据相对路径、输出写入和成对比较可用，不证明重定位策略有效，也没有重新运行全部历史敏感性或多骑手规模实验。

## 入库检查

对待上传文本扫描了常见 GitHub token、AWS access key、私钥和显式秘密赋值模式，未发现匹配。确认原始数据 CSV、虚拟环境、缓存与新生成的逐单输出被 Git 忽略。复制来源与文件 SHA-256 保存在 `SOURCE_FILES.json`；本次上传清单为仓库根目录 `MANIFEST_SHA256.txt`。
