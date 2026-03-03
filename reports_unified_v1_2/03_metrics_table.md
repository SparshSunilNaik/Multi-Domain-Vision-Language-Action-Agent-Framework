# Detailed Metrics Table

| Scenario | OK | Steps | TYPE | CLICK | FB | Retry | Guard | Loop | Latency | Adherence |
|----------|-----|-------|------|-------|-----|-------|-------|------|---------|-----------|
| Store — Single Item Purchase | ✅ | 7 | 3 | 4 | 1 | 0 | 0 | N | 4.05s | 0.26 |
| Store — Multi Item Purchase | ✅ | 9 | 4 | 5 | 0 | 0 | 0 | N | 3.20s | 0.31 |
| Booking — Hotel Reservation | ✅ | 7 | 3 | 4 | 0 | 0 | 0 | N | 3.29s | 0.27 |
| Booking — Doctor Appointment | ❌ | 30 | 20 | 10 | 2 | 3 | 0 | N | 5.10s | 0.12 |

## v1.1 Comparison

| Scenario | v1.1 OK | v1.2 OK | v1.1 Steps | v1.2 Steps | Δ |
|----------|---------|---------|------------|------------|---|
| Store — Single Item Purchase | ✅ | ✅ | 8 | 7 | -1 |
| Store — Multi Item Purchase | ❌ | ✅ | 30 | 9 | -21 |
| Booking — Hotel Reservation | ❌ | ✅ | 4 | 7 | +3 |
| Booking — Doctor Appointment | ❌ | ❌ | 14 | 30 | +16 |
