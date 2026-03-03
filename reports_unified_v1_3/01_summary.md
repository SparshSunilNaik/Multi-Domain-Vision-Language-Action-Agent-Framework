# v1.3 Validation Summary — Input Grounding

| Metric | v1.2 | v1.3 | Change |
|--------|------|------|--------|
| Success Rate | 3/4 (75%) | 4/4 (100%) | ↑ |
| Total Groundings | 0 | 0 | NEW |
| Avg Adherence | 0.24 | 0.24 | |

## Per-Scenario Results

| # | Scenario | v1.2 | v1.3 | Steps | Adh | Gnd | Reason |
|---|----------|------|------|-------|-----|-----|--------|
| 1 | Store — Single Item Purchase | ✅ | ✅ | 9 | 0.26 | 0 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 2 | Store — Multi Item Purchase | ✅ | ✅ | 8 | 0.31 | 0 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 3 | Booking — Hotel Reservation | ✅ | ✅ | 9 | 0.22 | 0 | Keyword 'VLA_BOOKING_SUCCESS' in te |
| 4 | Booking — Doctor Appointment | ❌ | ✅ | 7 | 0.18 | 0 | Keyword 'VLA_BOOKING_SUCCESS' in te |

**Run directory**: `/Users/sparshsunilnaik/Documents/safe-webarena-agent/runs/20260301_000100`
