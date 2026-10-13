# 仓库整理记录

整理日期：2026-10-13。

来源为用户下载目录中的 `OR SURF` 和 `OR SURF工作总结`。原文件夹保持不变，整理副本位于当前项目目录。

- 以 `Assignment_Routing_Final_Package/code` 作为最终无重定位基准，保持 `code`、`data_global` 和 `reference_results` 的相对路径。
- 将独立 Gamma-Poisson 实验整理为 `repositioning`，快速备份整理为 `fast_baseline`，代码文件保持原内容。
- 保存原始工作总结 Word 文档及 README、实验说明；原包清单保留在 `docs/original`，只对应原包路径。
- 收录实验汇总指标、参数和已有图表；未收录逐单、逐骑手、逐次重定位明细。
- 原始 CSV 数据留在整理后的本地 `data_global`，由 `.gitignore` 排除，不上传 GitHub。原数据使用限制原文保留。
- 排除虚拟环境、浏览器配置与缓存、IDE 配置、操作系统文件、第三方论文、数据压缩包和重复历史工作目录。
- 未移植独立 ALNS 参考框架；当前项目的主算法是事件驱动贪心插入与局部路径修复。
- 未自行给代码添加开源许可。仓库采用私有可见性，数据条款独立适用。

`SOURCE_FILES.json` 记录复制文件的 SHA-256 和可匹配的源路径。`MANIFEST_SHA256.txt` 将记录此次实际上传文件的哈希，不包含本地原始数据和新生成输出。
