#!/usr/bin/env python3
"""
Interactive VLA Demo — Unified multi-domain entry point.

Two modes:
  --interactive   Free-form prompt mode (routes to appropriate system)
  --full-demo     Scripted showcase across ALL supported domains

Usage:
    python interactive_vla_demo.py --interactive
    python interactive_vla_demo.py --full-demo
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
sys.path.insert(0, os.path.join(SCRIPT_DIR, "llm_crud_v1"))


# ═══════════════════════════════════════════════════════════════
#  Route Detection
# ═══════════════════════════════════════════════════════════════

CRUD_KEYWORDS = {"create", "edit", "reply", "delete", "project", "issue",
                 "crud", "forum", "gitlab", "submission", "post"}
YOUTUBE_KEYWORDS = {"watch", "play", "youtube", "video"}

def detect_route(instruction):
    """Determine which system should handle this instruction."""
    words = set(re.findall(r'\w+', instruction.lower()))
    if words & CRUD_KEYWORDS:
        # Determine CRUD domain
        if words & {"gitlab", "project", "issue"}:
            return "crud_gitlab"
        if words & {"forum", "submission", "post", "reply"}:
            return "crud_forum"
        # Ambiguous CRUD — default to forum
        return "crud_forum"
    if words & YOUTUBE_KEYWORDS:
        return "composite"
    return "vla_agent"

def detect_start_url(instruction):
    """Auto-detect start URL from instruction keywords."""
    low = instruction.lower()
    if "wikipedia" in low:
        return "https://en.wikipedia.org"
    if "youtube" in low:
        return "https://www.youtube.com"
    if "github" in low:
        return "https://github.com"
    if "google" in low:
        return "https://www.google.com"
    if "forum" in low or "reddit" in low:
        return "http://localhost:9999"
    if "gitlab" in low:
        return "http://localhost:8023"
    if "store" in low or "shop" in low or "buy" in low or "notebook" in low:
        return "http://localhost:8001/index.html"
    if "book" in low or "hotel" in low or "reservation" in low:
        return "http://localhost:8002/step1_service.html"
    return "https://www.google.com"


# ═══════════════════════════════════════════════════════════════
#  Domain Runners
# ═══════════════════════════════════════════════════════════════

def run_vla_scenario(ctx, instruction, start_url, run_dir, max_steps=15):
    """Run a single VLA agent scenario. Returns result dict."""
    import vla_unified_agent_v1_3 as agent
    page = ctx.new_page()
    t0 = time.time()
    try:
        result = agent.run_scenario(
            page, "Demo", instruction, start_url,
            None, max_steps, run_dir, visual=True
        )
        result["runtime"] = round(time.time() - t0, 1)
        return result
    finally:
        try:
            page.close()
        except Exception:
            pass


def run_composite_scenario(ctx, instruction, run_dir):
    """Run via composite orchestrator (YouTube playback etc)."""
    from composite_orchestrator_v1_1 import decompose_interactive, run_composite
    t0 = time.time()
    print(f"\n  🧠 Decomposing: \"{instruction[:60]}\"...")
    plan = decompose_interactive(instruction)
    print(f"  Plan: {len(plan.get('steps', []))} steps")
    for j, s in enumerate(plan.get("steps", []), 1):
        pb = " 🎬" if s.get("playback") else ""
        print(f"    {j}. [{s.get('domain')}] {s.get('instruction', '?')[:50]}{pb}")
    sc = {
        "name": "Demo Composite",
        "composite_instruction": instruction,
        "final_completion_keyword": plan.get("final_completion_keyword", ""),
        "steps": plan["steps"],
    }
    r, keep_page = run_composite(ctx, sc, run_dir, visual=True)
    r["runtime"] = round(time.time() - t0, 1)
    # If video playing, wait
    if keep_page:
        print("\n  🎬 Browser is open. Video is playing.")
        try:
            input("  Press Enter when done watching... ")
        except (EOFError, KeyboardInterrupt):
            print()
        try:
            keep_page.close()
        except Exception:
            pass
    return {
        "name": r.get("name", "Composite"),
        "instruction": instruction,
        "domain": "composite",
        "success": r.get("success", False),
        "steps_taken": r.get("steps_total", 0),
        "reason": r.get("stop_reason", ""),
        "runtime": r["runtime"],
    }


def run_crud_forum(browser, run_dir, max_steps=20):
    """Run full Forum CRUD sequence using an existing browser."""
    from forum_crud_llm import ForumCRUD
    t0 = time.time()
    forum_user = os.environ.get("FORUM_USER", "MarvelsGrantMan136")
    forum_pass = os.environ.get("FORUM_PASS", "test1234")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        fc = ForumCRUD(page, run_dir, max_steps=max_steps,
                       username=forum_user, password=forum_pass, verbose=True)
        data = fc.run_all(allow_delete=False)
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    succ = data["total_success"]
    total = data["total_ops"]
    return {
        "name": "Forum CRUD",
        "instruction": "Full CRUD sequence (Login→Create→Edit→Reply)",
        "domain": "forum",
        "success": succ == total,
        "steps_taken": sum(r.get("steps", 0) for r in data["results"]),
        "reason": f"{succ}/{total} passed",
        "runtime": round(time.time() - t0, 1),
        "detail": data["results"],
    }


def run_crud_gitlab(browser, run_dir, max_steps=25):
    """Run full GitLab CRUD sequence using an existing browser."""
    from gitlab_crud_llm import GitLabCRUD
    t0 = time.time()
    gl_user = os.environ.get("GITLAB_USER", "root")
    gl_pass = os.environ.get("GITLAB_PASS", "Kite$7v_Mango!Q2-Quartz")
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    try:
        gc = GitLabCRUD(page, run_dir, max_steps=max_steps,
                        username=gl_user, password=gl_pass, verbose=True)
        data = gc.run_all(allow_delete=False)
    finally:
        try:
            ctx.close()
        except Exception:
            pass
    succ = data["total_success"]
    total = data["total_ops"]
    return {
        "name": "GitLab CRUD",
        "instruction": "Full CRUD sequence (Login→Create→Edit→Issue)",
        "domain": "gitlab",
        "success": succ == total,
        "steps_taken": sum(r.get("steps", 0) for r in data["results"]),
        "reason": f"{succ}/{total} passed",
        "runtime": round(time.time() - t0, 1),
        "detail": data["results"],
    }


# ═══════════════════════════════════════════════════════════════
#  Summary Printer
# ═══════════════════════════════════════════════════════════════

def print_result(r):
    """Print a single result line."""
    st = "✅" if r.get("success") else "❌"
    print(f"  {st}  {r.get('domain', '?'):<12} │ "
          f"{r.get('steps_taken', 0):>3} steps │ "
          f"{r.get('runtime', 0):>6.1f}s │ "
          f"{r.get('reason', '')[:40]}")


def print_summary_table(results):
    """Print the final summary table."""
    print()
    print("═" * 72)
    print("  FINAL SUMMARY")
    print("═" * 72)
    print(f"  {'Domain':<14} {'Success':<9} {'Steps':>6} {'Runtime':>9}   Reason")
    print(f"  {'─'*14} {'─'*9} {'─'*6} {'─'*9}   {'─'*30}")
    total = len(results)
    ok = 0
    for r in results:
        s = "✅" if r.get("success") else "❌"
        if r.get("success"):
            ok += 1
        print(f"  {r.get('domain', '?'):<14} {s:<9} "
              f"{r.get('steps_taken', 0):>6} "
              f"{r.get('runtime', 0):>8.1f}s   "
              f"{r.get('reason', '')[:30]}")
    print(f"  {'─'*72}")
    print(f"  Overall: {ok}/{total} ({100*ok//max(total,1)}%)")
    print("═" * 72)


# ═══════════════════════════════════════════════════════════════
#  INTERACTIVE MODE
# ═══════════════════════════════════════════════════════════════

def mode_interactive():
    """Free-form prompt mode — routes to appropriate system."""
    from playwright.sync_api import sync_playwright

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", f"demo_{ts}")
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("═" * 60)
    print("  ═══ LLM CRUD DEMO MODE ═══")
    print("  Interactive prompt — type instructions, we route them.")
    print(f"  Run dir: {run_dir}")
    print("═" * 60)

    results = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        try:
            while True:
                print()
                try:
                    instruction = input("  Enter instruction (or 'quit'): ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\n  Bye!")
                    break
                if not instruction or instruction.lower() in ("quit", "exit", "q"):
                    break

                try:
                    url_input = input("  Start URL (leave blank for auto-detect): ").strip()
                except (EOFError, KeyboardInterrupt):
                    break

                route = detect_route(instruction)
                start_url = url_input or detect_start_url(instruction)

                print(f"\n  🔀 Route: {route}")
                print(f"  🌐 URL:   {start_url}")
                time.sleep(1.0)

                r = None
                try:
                    if route == "crud_forum":
                        r = run_crud_forum(browser, run_dir)
                    elif route == "crud_gitlab":
                        r = run_crud_gitlab(browser, run_dir)
                    elif route == "composite":
                        r = run_composite_scenario(ctx, instruction, run_dir)
                    else:
                        r = run_vla_scenario(ctx, instruction, start_url, run_dir)
                except Exception as e:
                    r = {
                        "name": "Error", "instruction": instruction,
                        "domain": route, "success": False,
                        "steps_taken": 0, "reason": str(e)[:60],
                        "runtime": 0,
                    }

                if r:
                    print()
                    print_result(r)
                    results.append(r)

                time.sleep(1.0)

        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass

    if results:
        print_summary_table(results)


# ═══════════════════════════════════════════════════════════════
#  FULL DEMO MODE
# ═══════════════════════════════════════════════════════════════

# Scripted demo scenarios for each domain
DEMO_SCENARIOS = [
    {
        "name": "Wikipedia",
        "domain": "wikipedia",
        "type": "vla",
        "instruction": "Search for Alan Turing on Wikipedia.",
        "start_url": "https://en.wikipedia.org",
        "keyword": "/wiki/Alan_Turing",
        "max_steps": 10,
    },
    {
        "name": "YouTube",
        "domain": "youtube",
        "type": "composite",
        "instruction": "Search neural networks on YouTube and let me watch the first video.",
    },
    {
        "name": "Store",
        "domain": "store",
        "type": "vla",
        "instruction": "Buy one notebook.",
        "start_url": "http://localhost:8001/index.html",
        "keyword": None,
        "max_steps": 20,
    },
    {
        "name": "Booking",
        "domain": "booking",
        "type": "vla",
        "instruction": "Book a hotel reservation for tomorrow.",
        "start_url": "http://localhost:8002/step1_service.html",
        "keyword": None,
        "max_steps": 20,
    },
    {
        "name": "Forum CRUD",
        "domain": "forum",
        "type": "crud_forum",
        "instruction": "Full CRUD sequence.",
    },
    {
        "name": "GitLab CRUD",
        "domain": "gitlab",
        "type": "crud_gitlab",
        "instruction": "Full CRUD sequence.",
    },
    {
        "name": "Composite",
        "domain": "composite",
        "type": "composite",
        "instruction": "Find who created Python and then search that person on Google.",
    },
]


def mode_full_demo():
    """Scripted multi-domain showcase."""
    from playwright.sync_api import sync_playwright

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(SCRIPT_DIR, "runs", f"fulldemo_{ts}")
    os.makedirs(run_dir, exist_ok=True)

    print()
    print("═" * 60)
    print("  ═══ FULL DEMO MODE ═══")
    print("  Scripted multi-domain showcase")
    print(f"  Domains: {len(DEMO_SCENARIOS)}")
    print(f"  Run dir: {run_dir}")
    print("═" * 60)

    results = []
    t_global = time.time()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        ctx = browser.new_context(viewport={"width": 1280, "height": 720},
                                  locale="en-US")
        try:
            for i, sc in enumerate(DEMO_SCENARIOS, 1):
                name = sc["name"]
                sc_type = sc["type"]

                print()
                print("=" * 60)
                print(f"  DOMAIN: {name.upper()}")
                print(f"  [{i}/{len(DEMO_SCENARIOS)}] {sc['instruction'][:55]}")
                print("=" * 60)

                time.sleep(1.0)

                r = None
                try:
                    if sc_type == "vla":
                        r = run_vla_scenario(
                            ctx, sc["instruction"], sc["start_url"],
                            run_dir, max_steps=sc.get("max_steps", 15)
                        )
                        r["domain"] = sc["domain"]
                        r["name"] = name

                    elif sc_type == "composite":
                        r = run_composite_scenario(ctx, sc["instruction"], run_dir)
                        r["domain"] = sc["domain"]
                        r["name"] = name

                    elif sc_type == "crud_forum":
                        r = run_crud_forum(browser, run_dir)

                    elif sc_type == "crud_gitlab":
                        r = run_crud_gitlab(browser, run_dir)

                except Exception as e:
                    print(f"  ⚠ Error: {str(e)[:60]}")
                    r = {
                        "name": name, "instruction": sc["instruction"],
                        "domain": sc.get("domain", "?"), "success": False,
                        "steps_taken": 0, "reason": f"Error: {str(e)[:50]}",
                        "runtime": 0,
                    }

                if r:
                    print()
                    print_result(r)
                    results.append(r)

                # Pause between domains
                if i < len(DEMO_SCENARIOS):
                    time.sleep(1.0)

        finally:
            try:
                ctx.close()
                browser.close()
            except Exception:
                pass

    total_time = round(time.time() - t_global, 1)

    # Final summary
    print_summary_table(results)
    print(f"\n  Total runtime: {total_time}s")

    # Save results
    report_path = os.path.join(run_dir, "demo_results.json")
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "mode": "full-demo",
            "total_runtime": total_time,
            "results": results,
        }, f, indent=2, default=str)
    print(f"  📄 Results: {report_path}")
    print(f"  📁 Run dir: {run_dir}")


# ═══════════════════════════════════════════════════════════════
#  Main
# ═══════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(
        description="Interactive VLA Demo — Unified multi-domain entry point"
    )
    ap.add_argument("--interactive", action="store_true",
                    help="Free-form prompt mode")
    ap.add_argument("--full-demo", action="store_true",
                    help="Scripted multi-domain showcase")
    args = ap.parse_args()

    if not args.interactive and not args.full_demo:
        print()
        print("  === LLM CRUD DEMO MODE ===")
        print("  Select mode:")
        print("  1) Interactive (free-form prompts)")
        print("  2) Full Demo (scripted showcase)")
        print("  3) Exit")
        print()
        try:
            choice = input("  Choice [1/2/3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Bye!")
            return
        if choice == "1":
            args.interactive = True
        elif choice == "2":
            args.full_demo = True
        else:
            print("  Bye!")
            return

    if args.interactive:
        mode_interactive()
    elif args.full_demo:
        mode_full_demo()

    print()
    print("═" * 60)
    print("  MULTI-DOMAIN DEMO SYSTEM READY.")
    print("═" * 60)
    print()


if __name__ == "__main__":
    main()
