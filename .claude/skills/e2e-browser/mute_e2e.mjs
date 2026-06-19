/** PR #1 mute e2e: server group → bulk cmdb_ci upload → searchable rule picker
 *  → create per-server mute → currently-muted view → unmute → "mute all rules"
 *  toggle. data-testid driven (locale-agnostic). Prints MUTE_E2E_OK. */
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

  await p.goto(BASE + "/mutes");
  await p.waitForSelector(sel("mutes-page"));

  // 1. create server group
  await p.fill(sel("sg-name-input"), "db-tier");
  await p.click(sel("sg-create"));
  await p.waitForSelector(sel("sg-row"));
  assert((await p.locator(sel("sg-row")).count()) === 1, "group created");

  // 2. bulk upload cmdb_ci (radix select: open + pick option)
  await p.click(sel("bulk-group-select"));
  await p.click(sel("bulk-group-option"));
  // (frontend splits on whitespace/comma, so a malformed token has no space)
  await p.fill(sel("bulk-cmdb-input"), "CS_1\nCS_2\nCS_1\nbad!ci");
  await p.click(sel("bulk-upload"));
  await p.waitForSelector(sel("bulk-result"));
  const bulk = await p.locator(sel("bulk-result")).textContent();
  assert(/added 2/.test(bulk) && /rejected 1/.test(bulk), "added 2 (dedup CS_1), rejected bad!ci: " + bulk);
  // member count badge updated
  await p.waitForSelector(sel("sg-count", ':has-text("2")'));

  // 3. searchable rule picker → pick a seen alertname
  await p.fill(sel("rule-search"), "Host");
  await p.waitForSelector(sel("rule-option"));
  await p.click(sel("rule-option", ':has-text("HostOutOfMemory")'));

  // 4. per-server mute (target defaults to server) — transition: not muted → muted
  assert((await p.locator(sel("muted-empty")).count()) === 1, "starts with nothing muted");
  await p.fill(sel("mute-cmdb-input"), "CS_1");
  await p.click(sel("mute-create"));
  await p.waitForSelector(sel("muted-row"));
  const row = await p.locator(sel("muted-row")).first().textContent();
  assert(/CS_1/.test(row) && /HostOutOfMemory/.test(row), "muted row shows CS_1 × HostOutOfMemory");

  // 5. currently-muted view has exactly one
  assert((await p.locator(sel("muted-row")).count()) === 1, "one mute listed");

  // 6. unmute (transition: muted → not muted)
  await p.click(sel("unmute"));
  await p.waitForSelector(sel("muted-empty"));
  assert((await p.locator(sel("muted-row")).count()) === 0, "unmuted");

  // 7. "mute all rules" for a server (alertname=null); rule search disabled
  await p.check(sel("mute-all-rules"));
  assert(await p.locator(sel("rule-search")).isDisabled(), "rule search disabled in all-rules mode");
  await p.fill(sel("mute-cmdb-input"), "CS_2");
  await p.click(sel("mute-create"));
  await p.waitForSelector(sel("muted-row"));
  const all = await p.locator(sel("muted-row")).first().textContent();
  assert(/CS_2/.test(all), "all-rules mute for CS_2 created: " + all);

  console.log("MUTE_E2E_OK");
} catch (e) {
  await p.screenshot({ path: "/tmp/mute-fail.png" });
  console.error("FAILED:", e.message);
  process.exitCode = 1;
} finally {
  await b.close();
}
