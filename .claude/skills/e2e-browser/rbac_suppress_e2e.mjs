/** RBAC alignment + incident suppression e2e.
 *  Prereqs: seeded stack (see SKILL.md) + users admin/editor/viewer
 *  (password123) + one open incident titled "DiskFire on vault-01"
 *  (ingest + one correlate_pending pass).
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
let page; // for failure screenshot

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
  // ---------- Part A: RBAC per role ----------
  for (const [role, email, isAdmin, canEdit] of [
    ["admin", "admin@example.com", true, true],
    ["editor", "editor@example.com", false, true],
    ["viewer", "viewer@example.com", false, false],
  ]) {
    const context = await browser.newContext({ viewport: { width: 1380, height: 860 } });
    const p = await login(context, email);

    // nav: admin-only items
    const settingsLinks = await p.locator('nav a[href="/settings"]').count();
    const usersLinks = await p.locator('nav a[href="/users"]').count();
    assert(
      settingsLinks === (isAdmin ? 1 : 0) && usersLinks === (isAdmin ? 1 : 0),
      `${role}: nav admin items (settings=${settingsLinks}, users=${usersLinks})`,
    );

    // route guard: direct URL entry
    await p.goto(BASE + "/settings");
    await sleep(600);
    if (isAdmin) {
      assert(p.url().endsWith("/settings"), `${role}: /settings reachable`);
    } else {
      assert(p.url() === BASE + "/", `${role}: /settings redirected to / (got ${p.url()})`);
    }
    await p.goto(BASE + "/users");
    await sleep(600);
    assert(
      isAdmin ? p.url().endsWith("/users") : p.url() === BASE + "/",
      `${role}: /users route guard`,
    );

    // in-page actions: incident detail buttons on /ops
    await p.goto(BASE + "/ops");
    await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
    await p.locator('[data-testid="panel-incidents"] tbody tr').first().click();
    await p.waitForSelector('[data-testid="incident-detail"]');
    await sleep(400);
    const actionRows = await p.locator('[data-testid="incident-actions"]').count();
    assert(
      actionRows === (canEdit ? 1 : 0),
      `${role}: incident action row count=${actionRows}, expected ${canEdit ? 1 : 0}`,
    );
    await p.screenshot({ path: SHOT(`rbac-${role}-incident-detail`) });
    await p.keyboard.press("Escape");

    // receiver test-send button (editor+ only; one seeded receiver row)
    await p.goto(BASE + "/notifications");
    await p.waitForSelector('td:has-text("ops-slack")');
    await sleep(400);
    const testButtons = await p.locator('button:has-text("테스트")').count();
    assert(
      testButtons === (canEdit ? 1 : 0),
      `${role}: receiver test buttons=${testButtons}, expected ${canEdit ? 1 : 0}`,
    );
    await p.screenshot({ path: SHOT(`rbac-${role}-nav`) });
    log(`${role}: nav/routes/actions all consistent`);
    await context.close();
  }

  // ---------- Part B: suppression flow (editor) ----------
  const context = await browser.newContext({ viewport: { width: 1380, height: 860 } });
  const p = await login(context, "editor@example.com");
  const row = () =>
    p.locator('[data-testid="panel-incidents"] tbody tr', { hasText: "DiskFire" });

  // fired incident visible in the default ACTIVE list
  await p.goto(BASE + "/ops");
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  assert((await row().count()) === 1, "fired incident visible in active list");
  await p.screenshot({ path: SHOT("sup-1-active-visible") });
  log("incident fired -> visible in active list");

  // stays after refresh: no auto-disappear
  await p.reload();
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  assert((await row().count()) === 1, "incident still in active list after reload");
  log("still visible after refresh (no auto-disappear)");

  // suppress -> leaves active list
  await row().click();
  await p.waitForSelector('[data-testid="action-suppress"]');
  await p.click('[data-testid="action-suppress"]');
  await p.waitForSelector('[data-testid="incident-detail"] :text("suppressed")');
  await p.screenshot({ path: SHOT("sup-2-suppressed-detail") });
  await p.keyboard.press("Escape");
  await sleep(700);
  assert((await row().count()) === 0, "suppressed incident left the active list");
  await p.screenshot({ path: SHOT("sup-3-active-without") });
  log("suppress -> removed from active list");

  // visible under the suppressed filter
  await p.locator('[data-testid="panel-incidents"] button[role="combobox"]').click();
  await p.locator('div[role="option"]:has-text("suppressed")').click();
  await p.waitForSelector('[data-testid="panel-incidents"] tbody tr');
  assert((await row().count()) === 1, "incident listed under suppressed filter");
  await p.screenshot({ path: SHOT("sup-4-suppressed-filter") });
  log("suppressed filter shows the muted incident");

  // unsuppress -> returns to active
  await row().click();
  await p.waitForSelector('[data-testid="action-unsuppress"]');
  await p.click('[data-testid="action-unsuppress"]');
  await p.waitForSelector('[data-testid="action-suppress"]'); // status back to open
  await p.keyboard.press("Escape");
  await p.locator('[data-testid="panel-incidents"] button[role="combobox"]').click();
  await p.locator('div[role="option"]').first().click(); // back to "active"
  await sleep(700);
  assert((await row().count()) === 1, "unsuppressed incident back in active list");
  await p.screenshot({ path: SHOT("sup-5-back-active") });
  log("unsuppress -> back in active list");

  console.log("RBAC_SUPPRESS_E2E_OK");
} catch (err) {
  if (page) await page.screenshot({ path: SHOT("99-rbac-failure") });
  console.error("FAILED:", err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
