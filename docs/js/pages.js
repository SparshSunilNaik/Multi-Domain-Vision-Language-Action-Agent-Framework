/*
 * Simplified stand-ins for the sites the agent visits. Interactive elements carry
 * data-el keys; the agent "injects" numbered data-vla-id tags at extraction time,
 * the same way the repository's EXTRACT_JS does on real pages.
 */
(() => {
  "use strict";
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  const field = (key, label, value = "", kind = "text") =>
    `<label class="mp-field"><span>${esc(label)}</span><span class="mp-input el" data-el="${key}" data-kind="type" data-label="${esc(label)}" data-type="${kind}">${esc(value)}</span></label>`;
  const button = (key, label, cls = "") =>
    `<span class="mp-btn el ${cls}" data-el="${key}" data-kind="click" data-label="${esc(label)}">${esc(label)}</span>`;
  const link = (key, label) =>
    `<span class="mp-link el" data-el="${key}" data-kind="click" data-label="${esc(label)}">${esc(label)}</span>`;

  const PAGES = {
    store_home: {
      url: "localhost:8001/index.html",
      html: () => `
        <div class="mp mp-store">
          <div class="mp-bar"><b>Local Store</b><span>${link("nav-cart", "Cart (0)")}</span></div>
          <h3 class="mp-h">Stationery</h3>
          <div class="mp-grid">
            <div class="mp-card"><div class="mp-thumb t1"></div><b>Notebook</b><span>$4.99</span>${button("buy-notebook", "Buy Notebook")}</div>
            <div class="mp-card"><div class="mp-thumb t2"></div><b>Desk lamp</b><span>$19.00</span>${button("buy-lamp", "Buy Desk lamp")}</div>
            <div class="mp-card"><div class="mp-thumb t3"></div><b>Pen set</b><span>$6.50</span>${button("buy-pens", "Buy Pen set")}</div>
          </div>
        </div>`,
    },
    store_checkout: {
      url: "localhost:8001/checkout.html",
      html: (ctx) => `
        <div class="mp mp-store">
          <div class="mp-bar"><b>Local Store</b><span>${link("nav-back", "Back to shop")}</span></div>
          <h3 class="mp-h">Checkout</h3>
          <p class="mp-sub">1 × Notebook, $4.99</p>
          <div class="mp-form">
            ${field("f-name", "Full name", ctx.name || "")}
            ${field("f-email", "Email", ctx.email || "", "email")}
            ${field("f-address", "Address", ctx.address || "")}
            ${field("f-city", "City", ctx.city || "")}
          </div>
          ${button("place-order", "Place order", "mp-primary")}
        </div>`,
    },
    store_done: {
      url: "localhost:8001/confirmation.html",
      html: () => `
        <div class="mp mp-store mp-center">
          <div class="mp-check" aria-hidden="true">✓</div>
          <h3 class="mp-h">Order confirmed</h3>
          <p class="mp-sub">Your notebook is on its way.</p>
          <code class="mp-marker">VLA_ORDER_SUCCESS</code>
        </div>`,
    },
    wiki_home: {
      url: "en.wikipedia.org",
      html: (ctx) => `
        <div class="mp mp-wiki mp-center">
          <h3 class="mp-serif">Wikipedia</h3>
          <p class="mp-sub">The free encyclopedia</p>
          <div class="mp-search">${field("w-search", "Search Wikipedia", ctx.q || "")}${button("w-go", "Search")}</div>
        </div>`,
    },
    wiki_article: {
      url: "en.wikipedia.org/wiki/Python_(programming_language)",
      html: () => `
        <div class="mp mp-wiki">
          <h3 class="mp-serif mp-left">Python (programming language)</h3>
          <div class="mp-article">
            <p>Python is a high-level, general-purpose programming language. Its design philosophy emphasizes code readability with the use of significant indentation.</p>
            <table class="mp-infobox">
              <tr><th>Paradigm</th><td>Multi-paradigm</td></tr>
              <tr><th>Designed by</th><td><span class="mp-extract" data-el="infobox-designer">Guido van Rossum</span></td></tr>
              <tr><th>First appeared</th><td>20 February 1991</td></tr>
            </table>
          </div>
        </div>`,
    },
    google_home: {
      url: "www.google.com",
      html: (ctx) => `
        <div class="mp mp-search-home mp-center">
          <h3 class="mp-big">Search</h3>
          <div class="mp-search wide">${field("g-search", "Search", ctx.q || "")}${button("g-go", "Search")}</div>
        </div>`,
    },
    google_results: {
      url: "www.google.com/search?q=",
      html: (ctx) => {
        const q = ctx.q || "";
        return `
        <div class="mp mp-results">
          <div class="mp-qbar"><span class="mp-input static">${esc(q)}</span></div>
          <p class="mp-sub mp-left">About 1,240,000 results</p>
          <ul class="mp-res">
            <li><span class="mp-rlink">${esc(q)} - Wikipedia</span><span>en.wikipedia.org › wiki</span></li>
            <li><span class="mp-rlink">${esc(q)}: biography and work</span><span>britannica.com</span></li>
            <li><span class="mp-rlink">Interviews with ${esc(q)}</span><span>youtube.com</span></li>
          </ul>
        </div>`;
      },
    },
  };

  window.VLAPages = {
    get(name) { return PAGES[name]; },
    render(container, name, ctx = {}) {
      const p = PAGES[name];
      container.innerHTML = p.html(ctx);
      container.setAttribute("aria-hidden", "true");
      return p;
    },
  };
})();
