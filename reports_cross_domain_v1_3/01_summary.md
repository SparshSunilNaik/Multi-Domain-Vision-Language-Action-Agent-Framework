# Cross-Domain Evaluation Summary — v1.3

**Date**: 2026-03-01 14:38
**Run dir**: `/Users/sparshsunilnaik/Documents/safe-webarena-agent/runs/20260301_143408`
**Total time**: 286s

## Overall

| Metric | Value |
|--------|-------|
| Success Rate | 10/10 (100%) |
| Avg Steps (success) | 4.1 |
| Avg Latency | 4.50s |
| Avg Adherence | 0.30 |
| Total Groundings | 0 |

## Per-Scenario Results

| # | Domain | Scenario | OK | Steps | Adh | Reason |
|---|--------|----------|----|-------|-----|--------|
| 1 | wikipedia  | Wikipedia — Alan Turing | ✅ | 3 | 0.21 | Keyword '/wiki/Alan_Turing' in URL |
| 2 | wikipedia  | Wikipedia — Python Language | ✅ | 2 | 0.38 | Keyword '/wiki/Python' in URL |
| 3 | google     | Google — OpenAI Search | ✅ | 1 | 0.30 | Keyword 'search?q=' in URL |
| 4 | google     | Google — Climate Change Search | ✅ | 1 | 0.36 | Keyword 'search?q=' in URL |
| 5 | youtube    | YouTube — Neural Networks | ✅ | 1 | 0.33 | Keyword 'results?search_query=' in  |
| 6 | youtube    | YouTube — Python Tutorial | ✅ | 1 | 0.36 | Keyword 'results?search_query=' in  |
| 7 | store      | Store — Notebook Purchase | ✅ | 7 | 0.27 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 8 | store      | Store — Desk Lamp Purchase | ✅ | 9 | 0.27 | Keyword 'VLA_ORDER_SUCCESS' in text |
| 9 | booking    | Booking — Hotel Reservation | ✅ | 9 | 0.23 | Keyword 'VLA_BOOKING_SUCCESS' in te |
| 10 | booking    | Booking — Doctor Appointment | ✅ | 7 | 0.24 | Keyword 'VLA_BOOKING_SUCCESS' in te |
