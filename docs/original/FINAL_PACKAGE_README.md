# Assignment and Routing Final Experiment Package

本文件夹是当前保留的最终版实验包，默认不启用骑手重定位。核心代码位于 `code`，两份实验数据位于 `data_global`，基准结果位于 `reference_results`，完整复现说明位于 `documentation`。

## 最快复现方法

在 PowerShell 中进入本文件夹，然后执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\code\requirements.txt
python .\code\run_reproduction_experiments.py
python .\code\verify_reproduction.py
```

三组实验分别为 2,200 单和 120 名骑手、2,200 单和 100 名骑手，以及 17,867 单和 800 名骑手。输出写入 `reproduced_outputs`。

推荐使用 64 位 Python 3.10 或 3.11。完整参数、算法流程、数据字段、输出字段和扩展建议请阅读 Word 文档。
