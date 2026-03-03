# CRUD Auth Domain Evaluation — v1 Summary

**Date**: 2026-03-01 18:38
**Runtime**: 132s

## Overall Results

- **Domains tested**: 2
- **Total operations**: 10
- **Successful**: 10/10 (100%)
- **Average latency**: 12.96s

## Per-Domain Results

| Domain | Login | Create | Edit | Reply/Issue | Delete | Total | Avg Lat |
|--------|-------|--------|------|-------------|--------|-------|--------|
| FORUM | ✅ | ✅ | ✅ | ✅ | ✅ | 5/5 | 8.43s |
| GITLAB | ✅ | ✅ | ✅ | ✅ | ✅ | 5/5 | 17.5s |

## Verification Strategy

All verifications are **DOM-based** (not URL-based):
- **CREATE**: Check that created content text appears in `document.body.innerText`
- **EDIT**: Check that updated content text appears in DOM after save
- **REPLY/ISSUE**: Check that reply/issue text appears in DOM
- **DELETE**: Check that content text is **absent** from listing page DOM
