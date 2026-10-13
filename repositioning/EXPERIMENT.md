# Route-fit rider-selection experiment

This version starts from the 2026-08-20 fast optimized baseline but replaces the
"nearest rider" part of the three-rule rider shortlist.

Default shortlist:

- 4 riders with the smallest exact route-distance increase after inserting both
  pickup and delivery across every legal gap in their remaining route;
- 2 riders with the lowest active order count;
- 2 riders with the earliest estimated pickup time.

To control runtime, exact route-fit traversal uses a 256-rider wide prefilter by
default (128 near merchant + 96 early pickup + 32 low load, deduplicated and
filled). Use `--route-fit-prefilter-riders 0` to calculate route fit for every
eligible rider. This shortlist score uses distance only; the final insertion
choice still uses the full weighted system marginal objective and on-time
protection.

Main-data comparison (17,867 orders, 800 riders):

| Version | On-time rate | Rejected | Distance km | Lateness min | Runtime sec |
|---|---:|---:|---:|---:|---:|
| Retained fast baseline | 69.70% | 113 | 41,512.39 | 339,198.85 | 97.58 |
| Route fit, 64-rider prefilter | 75.38% | 8 | 33,409.85 | 151,929.05 | 102.71 |
| Route fit, 256-rider prefilter (default) | 77.68% | 3 | 31,397.19 | 117,724.68 | 181.15 |
| Route fit, every eligible rider | 77.78% | 10 | 31,838.52 | 116,962.59 | 395.95 |

The 256-rider version is the default because it is only 0.10 percentage points
behind full traversal, while using less than half its runtime and producing a
lower realized weighted objective.
