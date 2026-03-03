"""Minimal accessibility-tree observation script against the forum container."""
import os
import sys

# Set required environment variables (dummy values for non-forum sites)
os.environ["REDDIT"] = "http://localhost:9999"
os.environ["SHOPPING"] = "http://localhost:9999"
os.environ["SHOPPING_ADMIN"] = "http://localhost:9999"
os.environ["GITLAB"] = "http://localhost:9999"
os.environ["WIKIPEDIA"] = "http://localhost:9999"
os.environ["MAP"] = "http://localhost:9999"
os.environ["HOMEPAGE"] = "http://localhost:9999"

# Now import browser_env (env_config.py asserts all env vars are set)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "third_party", "webarena"))

from browser_env import ScriptBrowserEnv

def main():
    print("Creating ScriptBrowserEnv with accessibility_tree observation...")
    env = ScriptBrowserEnv(
        headless=True,
        observation_type="accessibility_tree",
        current_viewport_only=False,
        viewport_size={"width": 1280, "height": 720},
    )

    print("Resetting environment (launches browser, opens blank page)...")
    obs, info = env.reset()

    # Navigate to the forum
    from browser_env.actions import create_goto_url_action
    action = create_goto_url_action("http://localhost:9999")
    obs, reward, terminated, truncated, info = env.step(action)

    # Extract accessibility tree text
    text_obs = obs.get("text", "")
    print(f"\n{'='*60}")
    print(f"Accessibility tree (first 2000 chars):")
    print(f"{'='*60}")
    print(text_obs[:2000])
    print(f"{'='*60}")
    print(f"\nTotal accessibility tree length: {len(text_obs)} chars")
    print(f"Page URL: {info['page'].url}")
    print(f"Reward: {reward}")

    print("\nClosing environment...")
    env.close()
    print("Done. Accessibility tree printed successfully.")

if __name__ == "__main__":
    main()
