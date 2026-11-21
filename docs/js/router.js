/*
 * Live port of detect_route() and detect_start_url() from interactive_vla_demo.py.
 */
(() => {
  "use strict";
  const CRUD_KEYWORDS = new Set(["create", "edit", "reply", "delete", "project", "issue", "crud", "forum", "gitlab", "submission", "post"]);
  const YOUTUBE_KEYWORDS = new Set(["watch", "play", "youtube", "video"]);
  const GITLAB = new Set(["gitlab", "project", "issue"]);
  const FORUM = new Set(["forum", "submission", "post", "reply"]);

  const words = (s) => s.toLowerCase().match(/\w+/g) || [];

  function detectRoute(instruction) {
    const w = new Set(words(instruction));
    const hit = (set) => [...w].filter((x) => set.has(x));
    if (hit(CRUD_KEYWORDS).length) {
      if (hit(GITLAB).length) return { route: "crud_gitlab", matched: hit(CRUD_KEYWORDS) };
      if (hit(FORUM).length) return { route: "crud_forum", matched: hit(CRUD_KEYWORDS) };
      return { route: "crud_forum", matched: hit(CRUD_KEYWORDS), note: "ambiguous CRUD, defaults to forum" };
    }
    if (hit(YOUTUBE_KEYWORDS).length) return { route: "composite", matched: hit(YOUTUBE_KEYWORDS) };
    return { route: "vla_agent", matched: [] };
  }

  function detectStartUrl(instruction) {
    const low = instruction.toLowerCase();
    if (low.includes("wikipedia")) return "en.wikipedia.org";
    if (low.includes("youtube")) return "www.youtube.com";
    if (low.includes("github")) return "github.com";
    if (low.includes("google")) return "www.google.com";
    if (low.includes("forum") || low.includes("reddit")) return "localhost:9999";
    if (low.includes("gitlab")) return "localhost:8023";
    if (["store", "shop", "buy", "notebook"].some((k) => low.includes(k))) return "localhost:8001/index.html";
    if (["book", "hotel", "reservation"].some((k) => low.includes(k))) return "localhost:8002/step1_service.html";
    return "www.google.com";
  }

  const input = document.getElementById("router-input");
  const tokensEl = document.getElementById("router-tokens");
  const lanes = [...document.querySelectorAll(".lane")];

  function update() {
    const text = input.value;
    const { route, matched, note } = detectRoute(text);
    const m = new Set(matched);
    tokensEl.innerHTML = (text.match(/\w+|[^\w]+/g) || [])
      .map((t) => {
        const safe = t.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
        return m.has(t.toLowerCase()) ? `<mark>${safe}</mark>` : safe;
      }).join("") || "&nbsp;";
    const lane = route.startsWith("crud") ? "crud" : route;
    lanes.forEach((l) => l.classList.toggle("is-active", l.dataset.route === lane));
    document.querySelectorAll(".pill[data-sub]").forEach((p) => p.classList.toggle("is-active", p.dataset.sub === route));
    document.getElementById("route-name").textContent = route;
    document.getElementById("route-url").textContent = detectStartUrl(text);
    document.getElementById("route-why").textContent = matched.length ? matched.join(", ") + (note ? ` (${note})` : "") : "no keywords, so the unified agent";
  }

  input.addEventListener("input", update);
  document.querySelectorAll("[data-ex]").forEach((b) => b.addEventListener("click", () => { input.value = b.dataset.ex; update(); }));
  update();
})();
