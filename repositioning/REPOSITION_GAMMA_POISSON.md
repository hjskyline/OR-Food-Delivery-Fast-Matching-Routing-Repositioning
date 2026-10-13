# Gamma-Poisson Repositioning Version

## Version boundary

This is an independent copy of `assignment_routing_route_fit_experiment`. The
two retained assignment/routing versions in the parent directory are unchanged.
The supplied source is preserved unchanged at
`reference/2_idle_relocation_poisson_6.py` for traceability.

Only its relocation idea was ported. Its ALNS solver and separate PDPTW
framework were not imported, because those would replace the current
assignment/routing method and invalidate a controlled comparison.

## Unchanged assignment and routing

- Event-driven greedy assignment with weighted insertion.
- Manhattan distance, 20 km/h, and eight active orders per rider.
- The 256-rider route-fit prefilter and exact route-increase shortlist.
- Deadline protection, high-risk expansion, active rejection, and local
  precedence-safe route optimization.

## Added relocation logic

At a relocation decision, the policy:

1. Uses only orders released by that time; future orders cannot enter the
   forecast or hotspot coordinates.
2. Estimates zone arrivals with a Gamma-Poisson posterior using a 20-minute
   recent window and a 15-minute forecast horizon.
3. Builds time-decayed merchant hotspots from the last 60 minutes with a
   30-minute exponential decay.
4. Converts idle and soon-free riders into order-equivalent supply using the
   observed direct service time of each zone.
5. Smooths zone late risk with a Bayesian prior.
6. Admits a move only when expected net on-time gain is at least 0.05 order and
   predicted improvement in the unchanged composite objective is at least ten.
   Feasible moves are ranked by the composite-objective delta.
7. Applies a 2.5-kilometre and six-minute travel limit, a 15-minute cooldown,
   two-rider source reserve, and a five-percent moved-rider limit.

Relocation consumes real distance and time. If an order is assigned during a
move, routing starts from the rider's interpolated position. `zone_id=-1` is
excluded from Gamma-Poisson demand estimation.

## Run and compare

Gamma-Poisson is the command-line default in this directory:

```powershell
python run_baseline.py --input ..\data_global\merchant_data_full_with_zones_global.csv --fleet-size 800 --output-dir outputs\full_gamma
```

Run a strict control with `--reposition-policy none`, or run both automatically:

```powershell
python run_reposition_comparison.py --input ..\data_global\merchant_data_2200_with_zones_global.csv --fleet-size 120 --output-dir outputs\global_2200_comparison
```

The wrapper creates full outputs under `without_reposition` and
`with_gamma_poisson`, plus `comparison.csv`.

## Current validation result

On the 2,200-order dataset with 120 riders, the initial aggressive
Gamma-Poisson policy made 67 moves and added 133.00 km. Overall on-time delivery
changed from 84.91% to 84.27%. The later protected default made one move and
kept on-time delivery at 84.91%. Both results are retained transparently.

## On-time protection experiment

The conservative protected policy was tested on 17,867 orders and 800 riders.
It made 11 moves over 16.48 km. Completion, rejected orders, on-time rate
(77.68%), and total lateness were unchanged; actual composite cost increased by
14.51 because of residual relocation distance.

A moderate sensitivity run lowered the expected net on-time gate to 0.01 and
the objective margin to zero, with a 7.5-minute travel limit, ten-percent tick
limit, and ten-minute cooldown. It made 29 moves and increased on-time delivery
from 77.68% to 77.86%, but rejected orders rose from three to seven and actual
composite cost increased by 2,201.47. This sensitivity result is retained for
diagnosis but is not the default policy.

Each run keeps the existing eight output files. `reposition_events.csv` also
reports the prediction model, recent/cumulative zone counts, service capacity,
arrival weight, expected covered/exposed orders, smoothed late risks, expected
avoided late orders, and secondary relocation cost.
