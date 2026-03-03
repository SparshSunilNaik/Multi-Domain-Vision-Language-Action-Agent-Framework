#!/usr/bin/env python3
"""
Run LLM CRUD Suite — CLI orchestrator for Forum + GitLab LLM-driven CRUD.

Usage:
  python run_llm_crud_suite.py --domains forum gitlab --max-steps 35
  python run_llm_crud_suite.py --domains forum gitlab --max-steps 35 --allow-delete
"""

import argparse, json, os, sys, time
from datetime import datetime
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="LLM CRUD Evaluation Suite")
    parser.add_argument("--domains", nargs="+", default=["forum", "gitlab"],
                        choices=["forum", "gitlab"])
    parser.add_argument("--max-steps", type=int, default=35)
    parser.add_argument("--allow-delete", action="store_true")
    parser.add_argument("--temperature", type=float, default=0.7)
    parser.add_argument("--model", default="qwen3:8b")
    parser.add_argument("--verbose", action="store_true", default=True)
    args = parser.parse_args()

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = Path(__file__).parent
    run_dir = str(base / "runs" / run_id)
    os.makedirs(run_dir, exist_ok=True)

    print("\n" + "═" * 60)
    print("  LLM CRUD EVALUATION SUITE")
    print("═" * 60)
    print(f"  Domains:    {', '.join(args.domains)}")
    print(f"  Max steps:  {args.max_steps}")
    print(f"  Delete:     {'YES' if args.allow_delete else 'NO'}")
    print(f"  Model:      {args.model}")
    print(f"  Temp:       {args.temperature}")
    print(f"  Run dir:    {run_dir}")
    print("═" * 60)

    from playwright.sync_api import sync_playwright
    all_results = {}
    t_start = time.time()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        if "forum" in args.domains:
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            from forum_crud_llm import ForumCRUD
            forum_user = os.environ.get("FORUM_USER", "MarvelsGrantMan136")
            forum_pass = os.environ.get("FORUM_PASS", "test1234")
            fc = ForumCRUD(
                page, run_dir, max_steps=args.max_steps,
                temperature=args.temperature,
                username=forum_user, password=forum_pass,
                verbose=args.verbose,
            )
            all_results["forum"] = fc.run_all(allow_delete=args.allow_delete)
            ctx.close()

        if "gitlab" in args.domains:
            ctx = browser.new_context(viewport={"width": 1280, "height": 800})
            page = ctx.new_page()
            from gitlab_crud_llm import GitLabCRUD
            gl_user = os.environ.get("GITLAB_USER", "root")
            gl_pass = os.environ.get("GITLAB_PASS", "Kite$7v_Mango!Q2-Quartz")
            gc = GitLabCRUD(
                page, run_dir, max_steps=args.max_steps,
                temperature=args.temperature,
                username=gl_user, password=gl_pass,
                verbose=args.verbose,
            )
            all_results["gitlab"] = gc.run_all(allow_delete=args.allow_delete)
            ctx.close()

        browser.close()

    total_time = round(time.time() - t_start, 1)

    # ── Summary table ──
    print("\n" + "═" * 64)
    print("  LLM CRUD RESULTS")
    print("═" * 64)
    print(f"  {'Domain':<10} {'Login':<7} {'Create':<8} {'Edit':<7} "
          f"{'Rply/Iss':<9} {'Delete':<8} {'Total':<7}")
    print(f"  {'─'*10} {'─'*6} {'─'*7} {'─'*6} {'─'*8} {'─'*7} {'─'*6}")

    overall_pass = 0
    overall_total = 0

    for domain, data in all_results.items():
        rs = data["results"]
        cols = {r["op"]: "✅" if r["success"] else "❌" for r in rs}
        login = cols.get("LOGIN", "—")
        create = cols.get("CREATE", "—")
        edit = cols.get("EDIT", "—")
        ri = cols.get("REPLY", cols.get("ISSUE", "—"))
        delete = cols.get("DELETE", "—")
        succ = data["total_success"]
        total = data["total_ops"]
        overall_pass += succ
        overall_total += total
        print(f"  {domain.upper():<10} {login:<7} {create:<8} {edit:<7} "
              f"{ri:<9} {delete:<8} {succ}/{total}")

    print(f"\n  Overall: {overall_pass}/{overall_total} "
          f"({100*overall_pass//max(overall_total,1)}%)  |  Runtime: {total_time}s")

    # ── Write report ──
    report_dir = str(base / "reports")
    os.makedirs(report_dir, exist_ok=True)
    report_path = os.path.join(report_dir, f"report_{run_id}.md")

    lines = [
        f"# LLM CRUD Evaluation Report",
        f"**Run ID**: {run_id}  ",
        f"**Date**: {datetime.now().isoformat()}  ",
        f"**Model**: {args.model}  ",
        f"**Temperature**: {args.temperature}  ",
        f"**Max steps**: {args.max_steps}  ",
        f"**Allow delete**: {args.allow_delete}  ",
        "",
        "## Architecture",
        "- **Agent**: LLM-driven DOM agent (`llm_dom_agent.py`)",
        "- **DOM extraction**: JS-based, injects `data-vla-id` for targeting",
        "- **LLM**: Ollama `/api/chat` with `think:false`",
        "- **Actions**: CLICK, TYPE, STOP — chosen by LLM from element list",
        "- **Verification**: Deterministic DOM text checks",
        "",
        "## Results",
        "",
        "| Domain | Op | Status | Steps | Latency | Reason |",
        "|--------|----|--------|-------|---------|--------|",
    ]

    for domain, data in all_results.items():
        for r in data["results"]:
            st = "✅" if r["success"] else "❌"
            lines.append(
                f"| {domain.upper()} | {r['op']} | {st} | "
                f"{r.get('steps',0)} | {r.get('latency',0):.1f}s | "
                f"{r.get('reason','')[:50]} |"
            )

    lines += [
        "",
        f"**Overall: {overall_pass}/{overall_total}**  ",
        f"**Runtime: {total_time}s**",
        "",
        "## Screenshots & Traces",
        f"- Screenshots: `{run_dir}/<domain>/<scenario>/step_##.png`",
        f"- Trace JSON: `{run_dir}/<domain>/<scenario>_trace.json`",
    ]

    # Failure modes
    failures = []
    for domain, data in all_results.items():
        for r in data["results"]:
            if not r["success"]:
                failures.append(f"- **{domain.upper()} {r['op']}**: {r.get('reason','')}")
    if failures:
        lines += ["", "## Failure Modes", ""] + failures

    with open(report_path, "w") as f:
        f.write("\n".join(lines))

    # ── Write JSON ──
    json_path = os.path.join(report_dir, f"results_{run_id}.json")
    with open(json_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    print(f"\n  📄 Report:  {report_path}")
    print(f"  📄 JSON:    {json_path}")
    print(f"  📁 Run dir: {run_dir}")
    print("\n" + "═" * 60)
    print("  LLM CRUD SUITE COMPLETE.")
    print("═" * 60 + "\n")

    # Exit code
    required_pass = overall_total
    if not args.allow_delete:
        # Don't count delete ops as required
        required_pass = sum(
            1 for d in all_results.values()
            for r in d["results"]
            if r["success"]
        )
    sys.exit(0 if overall_pass >= required_pass else 1)


if __name__ == "__main__":
    main()
