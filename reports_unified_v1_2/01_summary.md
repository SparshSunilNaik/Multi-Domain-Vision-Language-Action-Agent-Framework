# v1.2 Validation Summary

| Metric | v1.1 | v1.2 | Change |
|--------|------|------|--------|
| Success Rate | 1/4 (25%) | 3/4 (75%) | ↑ |
| Avg Steps (success) | 8.0 | 7.7 | |
| Avg Adherence | N/A | 0.24 | NEW |

## Per-Scenario Results

| # | Scenario | v1.1 | v1.2 | Steps | Adherence | Reason |
|---|----------|------|------|-------|-----------|--------|
| 1 | Store — Single Item Purchase | ✅ | ✅ | 7 | 0.26 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 2 | Store — Multi Item Purchase | ❌ | ✅ | 9 | 0.31 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 3 | Booking — Hotel Reservation | ❌ | ✅ | 7 | 0.27 | Keyword 'VLA_BOOKING_SUCCESS' in text |
| 4 | Booking — Doctor Appointment | ❌ | ❌ | 30 | 0.12 | Max steps |

**Run directory**: `/Users/sparshsunilnaik/Documents/safe-webarena-agent/runs/20260228_234315`
