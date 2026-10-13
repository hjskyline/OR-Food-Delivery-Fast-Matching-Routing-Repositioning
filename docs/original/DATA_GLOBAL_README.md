# Global-zone datasets

These are normalized project copies of the two datasets supplied on 2026-08-20.
The source files are preserved byte-for-byte; only the filenames were simplified.

## Files

- `merchant_data_2200_with_zones_global.csv`: 2,200 orders.
- `merchant_data_full_with_zones_global.csv`: 17,867 orders.

The 2,200-order dataset is an exact subset of the full dataset: all 2,200
`order_id` values and all 32 corresponding fields match.

## Change from the previous full dataset

The order, rider, time, and coordinate fields are unchanged. Only these fields
changed:

- `zone_id` changed for 16,872 of 17,867 orders.
- `hour_slot` changed from hourly values 10–13 to `-1` for every order.

This means the new `zone_id` was generated across the whole four-hour period,
rather than independently by hour. It is therefore the preferred spatial unit
for future repositioning comparisons across the small and full datasets.

The global full dataset contains 148 distinct `zone_id` values, including the
DBSCAN/noise label `-1`. There are 452 full-data orders and 71 small-data orders
with `zone_id = -1`. The current experiment loader does not create a relocation
target for `-1`; it assigns each noise order to the nearest valid merchant-zone
centroid for demand accounting.

`da_id` remains available as a coarser 20-area alternative.
