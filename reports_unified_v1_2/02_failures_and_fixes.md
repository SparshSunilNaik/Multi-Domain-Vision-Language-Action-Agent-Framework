# Failure Analysis & Fixes

## ❌ Booking — Doctor Appointment

- **Reason**: Max steps
- **Steps**: 30 | TYPE: 20 | CLICK: 10
- **Retries**: 3 | Guards: 0 | Fallbacks: 2
- **Loop**: No
- **Adherence**: 0.12

### Last 3 Actions

- Step 28: `TYPE (kb-fb) ← "next Monday"`
  Plan: - Fill the booking_date field with "next Monday".
- Fill the full_name field wit
- Step 29: `TYPE (kb-fb) ← "next Monday"`
  Plan: - Fill the booking_date field with "next Monday".
- Fill the full_name field wit
- Step 30: `TYPE (kb-fb) ← "next Monday"`
  Plan: - Fill the booking_date field with "next Monday".
- Fill the full_name field wit

## ✅ Successes

- **Store — Single Item Purchase**: 7 steps, adherence=0.26
- **Store — Multi Item Purchase**: 9 steps, adherence=0.31
- **Booking — Hotel Reservation**: 7 steps, adherence=0.27
