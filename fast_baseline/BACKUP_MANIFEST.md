# Fast optimized baseline backup (2026-08-20)

This directory is an independent snapshot of the retained fast algorithm before
the route-fit rider-selection experiment.

Reference run:

- Input: `merchant_data_full_with_zones.csv`
- Orders: 17,867
- Riders: 800, online for the full simulation
- Speed: 20 km/h
- Distance: rectilinear / Manhattan
- Maximum active orders per rider: 8
- Candidate composition: nearest 4 + lowest load 2 + earliest pickup 2
- Pickup/delivery insertion limit: 3 x 3; high-risk expansion 12 riders / 4 x 4
- Completed: 17,754; rejected: 113
- Overall on-time delivery rate: 69.7039%
- Total service distance: 41,512.3943 km
- Total lateness: 339,198.8485 minutes
- Weighted objective: 2,380,506.6369
- Runtime of the retained reference run: 97.5762 seconds

The small files needed to identify the reference result are under
`reference_output`. Historical and order-level outputs were deliberately not
duplicated.
