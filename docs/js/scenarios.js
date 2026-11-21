/*
 * Scenario scripts for the replay. Each mirrors a task from the repository's
 * evaluation suites (cross_domain_scenarios_v1_3.json, composite_scenarios_v2.json,
 * composite_orchestrator_v3.py) on simplified pages.
 */
window.VLAScenarios = {
  store: {
    firstPage: { name: "store_home" },
    async run(A) {
      await A.instr("Buy one notebook.");
      A.log("sys", "route: vla_agent, start localhost:8001");
      A.log("mem", "memory_store.json: name, email, address, city");
      await A.open("store_home");
      await A.extract();
      await A.plan(["Find the notebook product", "Click its Buy button"]);
      await A.click("buy-notebook");

      await A.open("store_checkout");
      await A.extract({ show: 3 });
      await A.warn("⚠ UNFILLED FIELDS: Full name, Email, Address, City");
      await A.plan(["Fill every field from the stored profile", "Then place the order"]);
      await A.type("f-name", "Asha Rao", { memory: "name" });
      await A.type("f-email", "asha@example.com", { memory: "email" });
      await A.type("f-address", "12 MG Road", { memory: "address" });
      await A.type("f-city", "Bengaluru", { memory: "city" });
      await A.plan(["All fields filled", "Submit the order"]);
      await A.click("place-order");

      await A.open("store_done");
      await A.verify("'VLA_ORDER_SUCCESS' found in page text");
    },
  },

  chain: {
    firstPage: { name: "wiki_home" },
    async run(A) {
      await A.instr("Find who created Python and search that person on Google.");
      A.log("sys", "route: composite orchestrator, decomposing with the LLM");
      await A.sleep(400);
      A.log("plan", "1. wikipedia: open Python, extract {{creator}}");
      await A.sleep(250);
      A.log("plan", "2. google: search {{creator}}");
      await A.sleep(400);

      await A.open("wiki_home");
      await A.extract();
      await A.plan(["Search for the Python programming language", "Open its article"]);
      await A.type("w-search", "Python programming language");
      await A.click("w-go");

      await A.open("wiki_article");
      await A.verify("'/wiki/Python' in URL");
      const creator = await A.extractVar("infobox-designer", "creator", "name");

      await A.open("google_home");
      A.log("var", `substitute {{creator}} → "${creator}"`);
      await A.extract();
      await A.plan([`Search for ${creator}`]);
      await A.type("g-search", creator);
      await A.click("g-go");

      await A.open("google_results", { q: creator, url: `www.google.com/search?q=${creator.replace(/ /g, "+")}` });
      await A.verify("'search?q=' in URL, chain complete");
    },
  },

  hitl: {
    firstPage: { name: "google_home" },
    async run(A) {
      await A.instr("Search for {{mystery_person}} on Google.");
      A.log("sys", "route: composite orchestrator v3");
      await A.sleep(400);
      A.log("var", "substitute variables and memory: {{mystery_person}} not found");
      await A.sleep(500);
      A.log("hitl", "HITL: missing variable, asking a human");
      const who = await A.hitl("Who is mystery_person?", ["Ada Lovelace", "Grace Hopper", "Alan Turing"]);
      A.log("var", `substitute {{mystery_person}} → "${who}"`);
      await A.sleep(400);

      await A.open("google_home");
      await A.extract();
      await A.plan([`Search for ${who}`]);
      await A.type("g-search", who);
      await A.click("g-go");

      await A.open("google_results", { q: who, url: `www.google.com/search?q=${encodeURIComponent(who).replace(/%20/g, "+")}` });
      await A.verify("'search?q=' in URL");
    },
  },
};
