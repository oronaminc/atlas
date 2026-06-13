/** Multi-tenancy e2e: HQ sees all tenants + filter dropdown; subsidiary
 *  user sees only their own; tenant CRUD + user reassignment in admin UI.
 *  Prereqs (see SKILL.md): HQ admin, tenants sub-a/sub-b (orgs org-a/org-b),
 *  sub-a editor ops-a@example.com, HQ viewer floater@example.com,
 *  2 incidents ingested via org-a + 1 via org-b.
 */
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const BASE = "http://127.0.0.1:5173";
const SHOT = (n) => `/tmp/shots/${n}.png`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const log = (m) => console.log("STEP:", m);
const assert = (cond, msg) => {
  if (!cond) throw new Error("ASSERT FAILED: " + msg);
};

const browser = await chromium.launch();
let page;

async function login(context, email) {
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  await page.goto(BASE + "/login");
  await page.fill("#email", email);
  await page.fill("#password", "password123");
  await page.click('button[type="submit"]');
  await page.waitForURL(BASE + "/");
  return page;
}

try {
  // ---------- HQ admin: sees ALL tenants ----------
  const hq = await browser.newContext({ viewport: { width: 1380, height: 860 } });
  let p = await login(hq, "admin@example.com");
  await p.goto(BASE + "/ops");
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  await sleep(600);
  let rows = await p.locator('[data-testid="panel-incidents"] tbody tr').count();
  assert(rows === 3, `HQ sees 3 incidents across tenants, got ${rows}`);
  assert(
    (await p.locator('[data-testid="tenant-filter"]').count()) === 1,
    "HQ sees the tenant filter dropdown",
  );
  // tenant column shows both slugs
  const body = await p.locator('[data-testid="panel-incidents"]').textContent();
  assert(body.includes("sub-a") && body.includes("sub-b"), "tenant column shows both slugs");
  await p.screenshot({ path: SHOT("ten-1-hq-all") });
  log("HQ: 3 incidents, both tenants visible + dropdown");

  // ---------- HQ: drill down to sub-a via dropdown ----------
  await p.locator('[data-testid="tenant-filter"]').click();
  await p.locator('div[role="option"]:has-text("sub-a")').click();
  await sleep(800);
  rows = await p.locator('[data-testid="panel-incidents"] tbody tr').count();
  assert(rows === 2, `sub-a filter shows 2 incidents, got ${rows}`);
  const filtered = await p.locator('[data-testid="panel-incidents"]').textContent();
  assert(!filtered.includes("db-b-01"), "sub-b incident hidden under sub-a filter");
  await p.screenshot({ path: SHOT("ten-2-hq-filtered-sub-a") });
  log("HQ: dropdown filter narrows to sub-a (2 incidents)");

  // ---------- HQ: tenants card in /settings ----------
  await p.goto(BASE + "/settings");
  await p.waitForSelector('[data-testid="tenants-card"]');
  assert(
    (await p.locator('[data-testid="tenant-row-sub-a"]').count()) === 1 &&
      (await p.locator('[data-testid="tenant-row-sub-b"]').count()) === 1,
    "tenants card lists sub-a and sub-b",
  );
  // create sub-c through the UI; ingest key shown once
  await p.click('[data-testid="tenant-create"]');
  await p.fill("#tenant-slug", "sub-c");
  await p.fill("#tenant-name", "Subsidiary C");
  await p.fill("#tenant-orgs", "org-c");
  await p.click('[data-testid="tenant-save"]');
  await p.waitForSelector('[data-testid="tenant-ingest-key"]');
  await p.screenshot({ path: SHOT("ten-3-tenant-created-key") });
  await p.keyboard.press("Escape");
  await p.waitForSelector('[data-testid="tenant-row-sub-c"]');
  log("HQ: created tenant sub-c via UI, ingest key shown once");

  // ---------- HQ: reassign floater -> sub-b in /users ----------
  await p.goto(BASE + "/users");
  await p.waitForSelector('[data-testid="tenant-select-floater"]');
  await p.locator('[data-testid="tenant-select-floater"]').click();
  await p.locator('div[role="option"]:has-text("sub-b")').click();
  await sleep(800);
  const sel = await p.locator('[data-testid="tenant-select-floater"]').textContent();
  assert(sel.includes("sub-b"), `floater now in sub-b, select shows "${sel}"`);
  await p.screenshot({ path: SHOT("ten-4-user-reassigned") });
  log("HQ: reassigned floater -> sub-b via users UI");
  await hq.close();

  // ---------- subsidiary user: own tenant only ----------
  const sub = await browser.newContext({ viewport: { width: 1380, height: 860 } });
  p = await login(sub, "ops-a@example.com");
  await p.goto(BASE + "/ops");
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  await sleep(600);
  rows = await p.locator('[data-testid="panel-incidents"] tbody tr').count();
  assert(rows === 2, `sub-a user sees exactly their 2 incidents, got ${rows}`);
  const subBody = await p.locator('[data-testid="panel-incidents"]').textContent();
  assert(!subBody.includes("db-b-01") && !subBody.includes("PacketLoss"), "zero tenant-B data");
  assert(
    (await p.locator('[data-testid="tenant-filter"]').count()) === 0,
    "no tenant dropdown for tenant users",
  );
  await p.screenshot({ path: SHOT("ten-5-sub-a-view") });
  log("sub-a user: 2 own incidents, zero tenant-B rows, no dropdown");

  // graph also scoped
  await p.goto(BASE + "/graph");
  await p.waitForSelector('[data-testid="swimlane-chart"]');
  await p.waitForSelector('[data-testid="incident-pill"]');
  const pills = await p.locator('[data-testid="incident-pill"]').count();
  assert(pills === 2, `graph shows only sub-a pills, got ${pills}`);
  log("sub-a user: graph scoped to own tenant");

  // floater (now sub-b) sees only the sub-b incident
  const fl = await browser.newContext({ viewport: { width: 1380, height: 860 } });
  p = await login(fl, "floater@example.com");
  await p.goto(BASE + "/ops");
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  await sleep(600);
  rows = await p.locator('[data-testid="panel-incidents"] tbody tr').count();
  const flBody = await p.locator('[data-testid="panel-incidents"]').textContent();
  assert(rows === 1 && flBody.includes("db-b-01"), "reassigned user sees sub-b's incident only");
  await p.screenshot({ path: SHOT("ten-6-floater-sub-b") });
  log("reassigned user: scoped to sub-b immediately");

  console.log("TENANCY_E2E_OK");
} catch (err) {
  if (page) await page.screenshot({ path: SHOT("99-tenancy-failure") });
  console.error("FAILED:", err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
