#!/usr/bin/env python3
"""
CRUD Runner — Runs Forum + GitLab CRUD evaluations and generates reports.

Usage:
    python auth_domain_crud_v1/crud_runner.py
    python auth_domain_crud_v1/crud_runner.py --forum-only
    python auth_domain_crud_v1/crud_runner.py --gitlab-only

Env vars:
    FORUM_USER, FORUM_PASS
    GITLAB_USER, GITLAB_PASS
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from forum_crud_agent import run_forum_crud
from gitlab_crud_agent import run_gitlab_crud

REPORTS_DIR = os.path.join(SCRIPT_DIR, "reports_crud_v1")
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)


# ═══════════════════════════════════════════════════════════════
#  Report Generation
# ═══════════════════════════════════════════════════════════════

def generate_reports(all_results, elapsed):
    os.makedirs(REPORTS_DIR, exist_ok=True)

    total_domains = len(all_results)
    total_ops = sum(r["total_ops"] for r in all_results)
    total_ok = sum(r["total_success"] for r in all_results)
    avg_lat = round(sum(r["avg_latency"] for r in all_results) / max(total_domains, 1), 2)

    # ── 01_summary.md ──
    sm = "# CRUD Auth Domain Evaluation — v1 Summary\n\n"
    sm += f"**Date**: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
    sm += f"**Runtime**: {elapsed:.0f}s\n\n"
    sm += "## Overall Results\n\n"
    sm += f"- **Domains tested**: {total_domains}\n"
    sm += f"- **Total operations**: {total_ops}\n"
    sm += f"- **Successful**: {total_ok}/{total_ops} ({total_ok/max(total_ops,1)*100:.0f}%)\n"
    sm += f"- **Average latency**: {avg_lat}s\n\n"

    sm += "## Per-Domain Results\n\n"
    sm += "| Domain | Login | Create | Edit | Reply/Issue | Delete | Total | Avg Lat |\n"
    sm += "|--------|-------|--------|------|-------------|--------|-------|--------|\n"

    for r in all_results:
        d = r["domain"].upper()
        login_ok = "✅" if r["results"][0]["success"] else "❌"
        create_ok = "✅" if r["create_success"] else "❌"
        edit_ok = "✅" if r["edit_success"] else "❌"
        ri_ok = "✅" if r["reply_or_issue_success"] else "❌"
        del_ok = "✅" if r["delete_success"] else "❌"
        tot = f"{r['total_success']}/{r['total_ops']}"
        lat = f"{r['avg_latency']}s"
        sm += f"| {d} | {login_ok} | {create_ok} | {edit_ok} | {ri_ok} | {del_ok} | {tot} | {lat} |\n"

    sm += "\n## Verification Strategy\n\n"
    sm += "All verifications are **DOM-based** (not URL-based):\n"
    sm += "- **CREATE**: Check that created content text appears in `document.body.innerText`\n"
    sm += "- **EDIT**: Check that updated content text appears in DOM after save\n"
    sm += "- **REPLY/ISSUE**: Check that reply/issue text appears in DOM\n"
    sm += "- **DELETE**: Check that content text is **absent** from listing page DOM\n"

    Path(REPORTS_DIR, "01_summary.md").write_text(sm)

    # ── Per-domain reports ──
    for r in all_results:
        idx = "02" if r["domain"] == "forum" else "03"
        fname = f"{idx}_{r['domain']}_results.md"

        rpt = f"# {r['domain'].upper()} CRUD Results\n\n"
        rpt += f"**Base URL**: {r['base_url']}\n\n"
        rpt += "## Operation Results\n\n"
        rpt += "| # | Operation | Status | Reason | Latency |\n"
        rpt += "|---|-----------|--------|--------|---------|\n"
        for i, op in enumerate(r["results"], 1):
            st = "✅" if op["success"] else "❌"
            rpt += f"| {i} | {op['operation']} | {st} | {op['reason'][:40]} | {op['latency']}s |\n"
        rpt += f"\n**Total**: {r['total_success']}/{r['total_ops']} operations succeeded\n"
        rpt += f"**Average latency**: {r['avg_latency']}s\n"

        Path(REPORTS_DIR, fname).write_text(rpt)


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="CRUD Auth Domain Runner")
    ap.add_argument("--forum-only", action="store_true")
    ap.add_argument("--gitlab-only", action="store_true")
    ap.add_argument("--headless", type=str, default="false")
    args = ap.parse_args()

    headless = args.headless.lower() in ("true", "1", "yes")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ playwright not installed")
        sys.exit(1)

    run_forum = not args.gitlab_only
    run_gitlab = not args.forum_only

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(PROJECT_ROOT, "runs", ts)
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("══════════════════════════════════════════════════════════")
    print("  CRUD AUTH DOMAIN EVALUATION — v1")
    print("══════════════════════════════════════════════════════════")
    print(f"  Forum:   {'YES' if run_forum else 'SKIP'}  │  "
          f"GitLab: {'YES' if run_gitlab else 'SKIP'}")
    print(f"  Headless: {headless}")
    print(f"  Run dir:  {run_dir}")
    print(f"  Env: FORUM_USER={'set' if os.environ.get('FORUM_USER') else '❌ NOT SET'}")
    print(f"       GITLAB_USER={'set' if os.environ.get('GITLAB_USER') else '❌ NOT SET'}")
    print("══════════════════════════════════════════════════════════")

    all_results = []
    t0 = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=headless)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720},
            locale="en-US",
        )

        try:
            if run_forum:
                ss_dir = os.path.join(run_dir, "screenshots_forum")
                os.makedirs(ss_dir, exist_ok=True)
                page = ctx.new_page()
                try:
                    forum_result = run_forum_crud(page, ss_dir)
                    all_results.append(forum_result)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

            if run_gitlab:
                ss_dir = os.path.join(run_dir, "screenshots_gitlab")
                os.makedirs(ss_dir, exist_ok=True)
                page = ctx.new_page()
                try:
                    gitlab_result = run_gitlab_crud(page, ss_dir)
                    all_results.append(gitlab_result)
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass

        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass

    elapsed = time.time() - t0

    if not all_results:
        print("\n  No results.")
        return

    # ── Save CSV ──
    csv_path = os.path.join(SCRIPT_DIR, "results_crud_v1.csv")
    with open(csv_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["domain", "create_success", "edit_success",
                     "reply_or_issue_success", "delete_success",
                     "total_success", "total_ops", "steps", "avg_latency"])
        for r in all_results:
            w.writerow([
                r["domain"], r["create_success"], r["edit_success"],
                r["reply_or_issue_success"], r["delete_success"],
                r["total_success"], r["total_ops"], r["steps"],
                r["avg_latency"],
            ])

    # ── Save JSON ──
    json_path = os.path.join(SCRIPT_DIR, "results_crud_v1.json")
    with open(json_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "runtime_seconds": round(elapsed, 1),
            "results": all_results,
        }, f, indent=2)

    # ── Generate Reports ──
    generate_reports(all_results, elapsed)

    # ── Console Summary ──
    total_ops = sum(r["total_ops"] for r in all_results)
    total_ok = sum(r["total_success"] for r in all_results)

    print()
    print("═" * 64)
    print("  CRUD RESULTS")
    print("═" * 64)
    print()
    print(f"  {'Domain':<10} {'Login':<7} {'Create':<8} {'Edit':<7} "
          f"{'Reply/I':<9} {'Delete':<8} {'Total':<8} {'Lat':<6}")
    print(f"  {'─'*10} {'─'*6} {'─'*7} {'─'*6} {'─'*8} {'─'*7} {'─'*7} {'─'*5}")

    for r in all_results:
        d = r["domain"].upper()
        cols = []
        for op_r in r["results"]:
            cols.append("✅" if op_r["success"] else "❌")
        # Pad to 5 columns
        while len(cols) < 5:
            cols.append("—")
        tot = f"{r['total_success']}/{r['total_ops']}"
        lat = f"{r['avg_latency']:.1f}s"
        print(f"  {d:<10} {cols[0]:<7} {cols[1]:<8} {cols[2]:<7} "
              f"{cols[3]:<9} {cols[4]:<8} {tot:<8} {lat:<6}")

    print()
    print(f"  Overall: {total_ok}/{total_ops} ({total_ok/max(total_ops,1)*100:.0f}%)")
    print(f"  Runtime: {elapsed:.1f}s")
    print()
    print(f"  📁 Reports:  {REPORTS_DIR}")
    print(f"  📁 CSV:      {csv_path}")
    print(f"  📁 JSON:     {json_path}")
    print(f"  📁 Run:      {run_dir}")
    print()
    print("══════════════════════════════════════════════════════════")
    print("  CRUD AUTH DOMAIN TEST COMPLETE. READY FOR SYSTEM INTEGRATION.")
    print("══════════════════════════════════════════════════════════")


if __name__ == "__main__":
    main()
