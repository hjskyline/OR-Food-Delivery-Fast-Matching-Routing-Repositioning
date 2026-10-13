# Local experiment data

本目录供本地放置合法取得的项目数据。原始 CSV 被 `.gitignore` 排除，未上传至 GitHub。

| 文件 | 唯一订单数 |
|---|---:|
| `merchant_data_2200_with_zones_global.csv` | 2,200 |
| `merchant_data_full_with_zones_global.csv` | 17,867 |

小数据是完整数据的精确子集。代码同时兼容小数经纬度和历史百万倍整数经纬度。全局 `zone_id` 跨四小时聚类，`-1` 为噪声标签；重定位处理以实际代码为准。

默认历史骑手重建模式所需字段：`order_id`、`waybill_id`、`courier_id`、`is_courier_grabbed`、`platform_order_time`、`order_push_time`、`estimate_meal_prepare_time`、`estimate_arrived_time`、`grab_time`、`fetch_time`、`arrive_time`、`sender_lng`、`sender_lat`、`recipient_lng`、`recipient_lat`、`grab_lng`、`grab_lat`。重定位还需相应分区字段，例如 `zone_id` 或 `da_id`。

独立骑手表可通过 `--courier-input` 指定，至少包含 `courier_id`、`start_lng` 和 `start_lat`。

原资料来自本地美团 INFORMS TSL 研究挑战数据目录。随附 [DATA_LICENSE.txt](DATA_LICENSE.txt) 要求非商业使用，并明确限制未经许可向第三方分发；请遵守原始条款并从获准来源取得数据。本仓库不重新授予数据使用权。

原始致谢要求：This research was supported by data provided by Meituan.
