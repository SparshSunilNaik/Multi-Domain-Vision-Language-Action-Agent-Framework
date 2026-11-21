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
};
