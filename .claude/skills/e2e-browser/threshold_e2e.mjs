/** PR #2 threshold e2e: rule-catalog metadata edit (comparator/unit/value_query,
 *  pass-through → configured transition) → per-server override → per-group
 *  override → precedence list → delete. data-testid driven (locale-agnostic).
 *  Requires seeded alert events (catalog rules) + one server group. Prints
 *  THRESHOLD_E2E_OK. */
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
const BASE = "http://127.0.0.1:5173";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1400, height: 950 } });
p.setDefaultTimeout(15000);
const assert = (c, m) => { if (!c) throw new Error("ASSERT: " + m); };
const sel = (testid, opt = "") => `[data-testid="${testid}"]${opt}`;
try {
  await p.goto(BASE + "/login");
  await p.fill("#email", "admin@example.com");
  await p.fill("#password", "password123");
  await p.click('button[type="submit"]');
  await p.waitForURL((u) => !u.pathname.endsWith("/login"));

  await p.goto(BASE + "/thresholds");
  await p.waitForSelector(sel("thresholds-page"));

  // 1. catalog: an un-configured rule shows the pass-through badge
  await p.fill(sel("catalog-search"), "Host");
  await p.waitForSelector(sel("catalog-rule"));
  const memRule = sel("catalog-rule", ':has-text("HostOutOfMemory")');
  await p.waitForSelector(memRule);
  const before = await p.locator(memRule).innerHTML();
  assert(/catalog-passthrough/.test(before), "rule starts as pass-through");

  // 2. configure metadata: comparator > , unit %, value_query with {{cmdb_ci}}
  await p.click(memRule);
  await p.waitForSelector(sel("catalog-form"));
  await p.click(sel("catalog-comparator"));
  await p.click(sel("cmp-gt"));
  await p.fill(sel("catalog-unit"), "%");
  await p.fill(sel("catalog-value-query"), 'mem_used{cmdb_ci="{{cmdb_ci}}"}');
  await p.click(sel("catalog-save"));
  // pass-through badge flips to configured (> %)
  await p.waitForSelector(sel("catalog-rule", ':has-text("HostOutOfMemory") >> ' + sel("catalog-configured")), { timeout: 15000 }).catch(() => {});
  await p.waitForFunction(() => {
    const rows = [...document.querySelectorAll('[data-testid="catalog-rule"]')];
    const r = rows.find((el) => el.textContent.includes("HostOutOfMemory"));
    return r && r.querySelector('[data-testid="catalog-configured"]');
  });

  // 3. per-server override (precedence tier=server)
  assert((await p.locator(sel("overrides-empty")).count()) === 1, "starts with no overrides");
  await p.click(sel("ovr-alert"));
  await p.click(sel("ovr-alert-option", ':has-text("HostOutOfMemory")'));
  // tier defaults to server
  await p.fill(sel("ovr-cmdb"), "CS_1");
  await p.fill(sel("ovr-value"), "95");
  await p.click(sel("ovr-create"));
  await p.waitForSelector(sel("override-row"));
  const srvRow = await p.locator(sel("override-row")).first().textContent();
  assert(/CS_1/.test(srvRow) && /95/.test(srvRow) && /HostOutOfMemory/.test(srvRow),
    "server override row shows CS_1 × HostOutOfMemory > 95: " + srvRow);

  // 4. per-group override (precedence tier=group)
  await p.click(sel("ovr-alert"));
  await p.click(sel("ovr-alert-option", ':has-text("HostOutOfMemory")'));
  await p.click(sel("ovr-tier"));
  await p.click(sel("tier-group"));
  await p.click(sel("ovr-group"));
  await p.locator('[role="option"]').first().click(); // pick the first group
  await p.fill(sel("ovr-value"), "80");
  await p.click(sel("ovr-create"));
  await p.waitForFunction(() => document.querySelectorAll('[data-testid="override-row"]').length === 2);
  assert((await p.locator(sel("override-row")).count()) === 2, "two overrides (server + group)");

  // 5. delete one override (transition 2 → 1)
  await p.locator(sel("override-delete")).first().click();
  await p.waitForFunction(() => document.querySelectorAll('[data-testid="override-row"]').length === 1);
  assert((await p.locator(sel("override-row")).count()) === 1, "one override after delete");

  console.log("THRESHOLD_E2E_OK");
} catch (e) {
  await p.screenshot({ path: "/tmp/threshold-fail.png" });
  console.error("FAILED:", e.message);
  process.exitCode = 1;
} finally {
  await b.close();
}
