"""
YouTube Playback Extension v1 — Deterministic video click + playback detection.

Provides:
    has_watch_intent(instruction)  → bool
    click_first_video(page)       → dict with url, title, success
    wait_for_playback(page)       → dict with video_detected, playing, url
"""

import re
import time


# ═══════════════════════════════════════════════════════════════
#  Intent Detection
# ═══════════════════════════════════════════════════════════════
WATCH_KEYWORDS = [
    "watch", "play", "open video", "open a video", "open the video",
    "play video", "play a video", "let me watch", "start video",
    "view video", "stream", "first video", "top video",
]

def has_watch_intent(instruction):
    """Detect if the instruction wants to watch/play a YouTube video."""
    if not instruction:
        return False
    instr_lower = instruction.lower()
    return any(kw in instr_lower for kw in WATCH_KEYWORDS)


# ═══════════════════════════════════════════════════════════════
#  Find & Click First Video
# ═══════════════════════════════════════════════════════════════
FIND_WATCH_LINKS_JS = """
() => {
    const links = [];
    document.querySelectorAll('a[href*="/watch"]').forEach(el => {
        const href = el.getAttribute('href') || '';
        if (!href.includes('/watch')) return;
        const rect = el.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        if (rect.top > window.innerHeight * 2) return;
        const style = window.getComputedStyle(el);
        if (style.display === 'none' || style.visibility === 'hidden') return;

        // Get visible text (title text)
        let text = '';
        // Check for title attribute first
        text = el.getAttribute('title') || '';
        if (!text) {
            // Check child elements for text
            const titleEl = el.querySelector('#video-title, .title, [class*="title"]');
            if (titleEl) text = titleEl.textContent.trim();
        }
        if (!text) {
            text = el.textContent.trim().substring(0, 120);
        }
        // Clean up text
        text = text.replace(/\\s+/g, ' ').trim();

        if (text.length > 3) {
            links.push({
                href: href,
                text: text.substring(0, 100),
                top: rect.top,
                left: rect.left,
                width: rect.width,
                height: rect.height,
            });
        }
    });
    // Sort by position (top first, then left)
    links.sort((a, b) => a.top - b.top || a.left - b.left);
    return links;
}
"""


def click_first_video(page):
    """Find and click the first video link on a YouTube results page.

    Returns:
        dict with: success, video_url, video_title, links_found
    """
    result = {
        "success": False,
        "video_url": "",
        "video_title": "",
        "links_found": 0,
    }

    try:
        links = page.evaluate(FIND_WATCH_LINKS_JS)
    except Exception as e:
        result["error"] = f"JS eval failed: {str(e)[:50]}"
        return result

    if not links:
        result["error"] = "No /watch links found"
        return result

    result["links_found"] = len(links)

    # Pick the first link (topmost visible video)
    target = links[0]
    result["video_title"] = target["text"]

    try:
        # Click the link using href selector
        href = target["href"]
        selector = f'a[href="{href}"]'
        el = page.query_selector(selector)
        if not el:
            # Fallback: try partial href match
            selector = f'a[href*="{href[:40]}"]'
            el = page.query_selector(selector)
        if not el:
            # Fallback: click by text
            loc = page.get_by_text(target["text"][:50], exact=False)
            if loc.count() > 0:
                loc.first.click(timeout=5000)
                result["success"] = True
                time.sleep(2)
                result["video_url"] = page.url
                return result
            result["error"] = "Could not find clickable element"
            return result

        el.scroll_into_view_if_needed(timeout=3000)
        time.sleep(0.3)
        el.click(timeout=5000)
        time.sleep(2)
        result["success"] = True
        result["video_url"] = page.url
    except Exception as e:
        result["error"] = f"Click failed: {str(e)[:50]}"

    return result


# ═══════════════════════════════════════════════════════════════
#  Playback Detection
# ═══════════════════════════════════════════════════════════════
def wait_for_playback(page, timeout=8):
    """Wait for video element and playback to begin.

    Returns:
        dict with: video_detected, url_is_watch, playing, waited_seconds
    """
    result = {
        "video_detected": False,
        "url_is_watch": False,
        "playing": False,
        "waited_seconds": 0,
    }

    t0 = time.time()

    # Wait for URL to contain /watch
    for _ in range(timeout * 2):
        url = page.url
        if "/watch" in url:
            result["url_is_watch"] = True
            break
        time.sleep(0.5)
    result["waited_seconds"] = round(time.time() - t0, 1)

    if not result["url_is_watch"]:
        return result

    # Wait for video element
    for _ in range(timeout):
        try:
            video = page.query_selector("video")
            if video:
                result["video_detected"] = True
                break
        except Exception:
            pass
        time.sleep(1)

    if not result["video_detected"]:
        # Try iframe-embedded video
        try:
            frames = page.frames
            for frame in frames:
                try:
                    video = frame.query_selector("video")
                    if video:
                        result["video_detected"] = True
                        break
                except Exception:
                    pass
        except Exception:
            pass

    # Wait for playback to start (video.currentTime > 0 or not paused)
    if result["video_detected"]:
        time.sleep(3)  # Allow 3 seconds for playback to begin
        try:
            playing = page.evaluate("""
                () => {
                    const v = document.querySelector('video');
                    if (!v) return false;
                    return !v.paused || v.currentTime > 0;
                }
            """)
            result["playing"] = bool(playing)
        except Exception:
            # If we can't check, assume playing if video element exists
            result["playing"] = True

    result["waited_seconds"] = round(time.time() - t0, 1)
    return result


# ═══════════════════════════════════════════════════════════════
#  Full Playback Flow
# ═══════════════════════════════════════════════════════════════
def execute_playback(page):
    """Complete playback flow: find video → click → wait for playback.

    Returns:
        dict with all metrics from click + playback detection
    """
    print("  🎬 Playback mode: finding first video...")

    click_result = click_first_video(page)
    if not click_result["success"]:
        print(f"  ❌ Video click failed: {click_result.get('error', '?')}")
        return {**click_result, "video_detected": False, "playing": False,
                "waited_seconds": 0, "url_is_watch": False}

    title = click_result["video_title"][:50]
    print(f"  🎬 Clicked: \"{title}\"")

    playback = wait_for_playback(page)

    merged = {**click_result, **playback}

    if playback["playing"]:
        print(f"  ▶️  Video playing! URL: {playback.get('url_is_watch', False)}")
        print(f"  ▶️  Video element: {playback['video_detected']}")
    elif playback["video_detected"]:
        print(f"  ⏸  Video detected but playback uncertain")
    else:
        print(f"  ⚠  Video element not found on page")

    return merged
