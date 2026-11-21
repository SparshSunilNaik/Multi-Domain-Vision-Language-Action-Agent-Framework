/*
 * Results from the repository's report files. Each suite is a tab; tiles show
 * per-task outcome and step count, and reveal the stop reason when selected.
 */
(() => {
  "use strict";
  const SUITES = [
    {
      id: "cross",
      name: "Cross-domain v1.3",
      source: "reports_cross_domain_v1_3/01_summary.md, run of 1 March 2026",
      stats: [["Average steps", "4.1"], ["Average latency", "4.50 s"], ["Total time", "286 s"]],
      tasks: [
        ["Wikipedia", "Alan Turing", true, 3, "Keyword '/wiki/Alan_Turing' in URL"],
        ["Wikipedia", "Python language", true, 2, "Keyword '/wiki/Python' in URL"],
        ["Google", "OpenAI search", true, 1, "Keyword 'search?q=' in URL"],
        ["Google", "Climate change search", true, 1, "Keyword 'search?q=' in URL"],
        ["YouTube", "Neural networks", true, 1, "Keyword 'results?search_query=' in URL"],
        ["YouTube", "Python tutorial", true, 1, "Keyword 'results?search_query=' in URL"],
        ["Store", "Notebook purchase", true, 7, "'VLA_ORDER_SUCCESS' in page text"],
        ["Store", "Desk lamp purchase", true, 9, "'VLA_ORDER_SUCCESS' in page text"],
        ["Booking", "Hotel reservation", true, 9, "'VLA_BOOKING_SUCCESS' in page text"],
        ["Booking", "Doctor appointment", true, 7, "'VLA_BOOKING_SUCCESS' in page text"],
      ],
    },
    {
      id: "comp2",
      name: "Composite v2",
      source: "reports_composite_v2/report_20260303_113010.md",
      stats: [["Model", "qwen3:8b"], ["Runtime", "196.7 s"], ["Retries used", "1"]],
      tasks: [
        ["Wikipedia → Google", "Python creator → Google", true, 4, "All 2 steps done, final keyword matched (1 retry)"],
        ["Wikipedia → YouTube", "Alan Turing biography", true, 3, "Extracted {{birth_year}} = 1912, then searched YouTube"],
        ["Store", "Store purchase", true, 8, "All steps completed"],
        ["Booking", "Hotel booking", true, 7, "All steps completed"],
        ["Wikipedia → Google", "Wikipedia fact chain", true, 3, "All 2 steps done, final keyword matched"],
      ],
    },
    {
      id: "comp3",
      name: "Composite v3 + HITL",
      source: "reports_composite_v3/report_v3_20260303_115721.md",
      stats: [["Model", "qwen3:8b"], ["Runtime", "1184 s"], ["Failures", "3"]],
      tasks: [
        ["Wikipedia → Google", "Wikipedia extraction", true, 4, "All 2 steps done, final keyword matched (1 retry)"],
        ["Google", "Google search", true, 1, "All steps done, final keyword matched"],
        ["YouTube", "YouTube playback", true, 2, "YouTube playback started"],
        ["Store", "Store purchase", false, 15, "Step 1 failed: loop detected at the same URL"],
        ["Booking", "Booking reservation", true, 7, "All steps completed"],
        ["Forum", "Forum CRUD", false, 45, "3 of 4 operations passed"],
        ["GitLab", "GitLab CRUD", false, 0, "Error: page load timed out before the first step"],
        ["Wikipedia → Google", "Cross-domain chain", true, 3, "All 2 steps done, final keyword matched"],
        ["Google", "HITL: missing variable", true, 1, "All steps done, final keyword matched"],
        ["Booking", "HITL: missing city", true, 9, "All steps completed"],
      ],
    },
    {
      id: "crud",
      name: "LLM CRUD",
      source: "llm_crud_v1/reports/report_20260301_202512.md (GitLab) and report_20260301_210718.md (Forum), the final runs of 1 March",
      stats: [["Temperature", "0.7"], ["Max steps", "20"], ["Delete allowed", "No"]],
      tasks: [
        ["Forum", "Login", true, 1, "Logged in, 6.5 s"],
        ["Forum", "Create post", true, 4, "Post created, 17.7 s"],
        ["Forum", "Edit post", true, 4, "Edit marker visible, 23.5 s"],
        ["Forum", "Reply", true, 20, "Reply marker visible, 300.9 s"],
        ["GitLab", "Login", true, 1, "Logged in, 6.8 s"],
        ["GitLab", "Create project", true, 1, "Project created, 48.5 s"],
        ["GitLab", "Edit project", true, 4, "Edit marker in DOM, 72.9 s"],
        ["GitLab", "Open issue", true, 25, "Issue visible, 554.1 s"],
      ],
    },
  ];

  const tabsEl = document.getElementById("suite-tabs");
  const tilesEl = document.getElementById("tiles");
  const detail = document.getElementById("tile-detail");
  const arc = document.getElementById("score-arc");
  const C = 2 * Math.PI * 50;
  arc.style.strokeDasharray = `${C}`;
  arc.style.strokeDashoffset = `${C}`;

  const tabs = SUITES.map((s, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.role = "tab";
    b.id = `suite-tab-${s.id}`;
    b.setAttribute("aria-controls", "suite-panel");
    b.textContent = s.name;
    b.addEventListener("click", () => select(i));
    b.addEventListener("keydown", (e) => {
      const d = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
      if (d) { e.preventDefault(); select((i + d + SUITES.length) % SUITES.length, true); }
    });
    tabsEl.appendChild(b);
    return b;
  });

  function dots(n) {
    const shown = Math.min(n, 25);
    return `<span class="dots-row" aria-hidden="true">${"<i></i>".repeat(shown)}${n > 25 ? "<em>+" + (n - 25) + "</em>" : ""}</span>`;
  }

  function select(i, focus) {
    const s = SUITES[i];
    tabs.forEach((t, j) => { t.setAttribute("aria-selected", String(j === i)); t.tabIndex = j === i ? 0 : -1; });
    document.getElementById("suite-panel").setAttribute("aria-labelledby", tabs[i].id);
    if (focus) tabs[i].focus();

    const passed = s.tasks.filter((t) => t[2]).length;
    document.getElementById("score-num").textContent = `${passed}/${s.tasks.length}`;
    arc.style.strokeDashoffset = `${C * (1 - passed / s.tasks.length)}`;
    arc.classList.toggle("partial", passed < s.tasks.length);
    document.getElementById("suite-stats").innerHTML = s.stats.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
    document.getElementById("suite-source").textContent = `Source: ${s.source}`;
    detail.textContent = "";

    tilesEl.innerHTML = s.tasks.map(([domain, name, ok, steps], k) => `
      <li style="--i:${k}">
        <button type="button" class="tile ${ok ? "ok" : "fail"}" data-k="${k}" aria-pressed="false">
          <span class="tile-top"><span class="tile-domain">${domain}</span><span class="tile-status">${ok ? "Passed" : "Failed"}</span></span>
          <span class="tile-name">${name}</span>
          ${dots(steps)}
          <span class="tile-steps">${steps} step${steps === 1 ? "" : "s"}</span>
        </button>
      </li>`).join("");
    tilesEl.querySelectorAll(".tile").forEach((b) => b.addEventListener("click", () => {
      tilesEl.querySelectorAll(".tile").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      const t = s.tasks[+b.dataset.k];
      detail.innerHTML = `<b>${t[1]}</b>: ${t[4]}`;
      detail.className = `tile-detail ${t[2] ? "ok" : "fail"}`;
    }));
  }

  select(0);
})();
