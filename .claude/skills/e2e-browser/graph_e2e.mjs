import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const BASE = "http://127.0.0.1:5173";
const SHOT = (n) => `/tmp/shots/${n}.png`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch(); // plain SVG — no WebGL flags needed
const page = await browser.newPage({ viewport: { width: 1380, height: 860 } });
page.setDefaultTimeout(15000);
const log = (m) => console.log("STEP:", m);
const assert = (cond, msg) => {
  if (!cond) throw new Error("ASSERT FAILED: " + msg);
};

try {
  // login
  await page.goto(BASE + "/login");
  await page.fill("#email", "admin@example.com");
  await page.fill("#password", "password123");
  await page.click('button[type="submit"]');
  await page.waitForURL(BASE + "/");
  log("logged in");

  // 1. /graph loads, swimlanes render
  await page.goto(BASE + "/graph");
  await page.waitForSelector('[data-testid="swimlane-chart"]');
  await page.waitForSelector('[data-testid="incident-pill"]');
  await sleep(500);
  const pillCount = await page.locator('[data-testid="incident-pill"]').count();
  assert(pillCount >= 10, `expected >=10 pills, got ${pillCount}`);
  await page.screenshot({ path: SHOT("g1-full-view") });
  log(`swimlanes rendered with ${pillCount} pills`);

  // 2. noisy host = top lane (db-01 has 3 open incidents)
  const lanes = page.locator('g[data-testid^="lane-"]');
  const firstLane = await lanes.first().getAttribute("data-testid");
  assert(firstLane === "lane-host=db-01", `top lane is ${firstLane}, expected lane-host=db-01`);
  const laneCount = await lanes.count();
  assert(laneCount === 12, `expected 12 visible lanes (cap), got ${laneCount}`);
  log(`noisy host on top: ${firstLane}; ${laneCount} lanes visible (capped)`);

  // 3. pills sized by first_seen->last_seen, severity fill
  const widthOf = async (title) => {
    const rect = page
      .locator(`g[data-testid="incident-pill"]:has-text("${title}")`)
      .locator("rect");
    return parseFloat(await rect.getAttribute("width"));
  };
  const fillOf = async (title) =>
    page
      .locator(`g[data-testid="incident-pill"]:has-text("${title}")`)
      .locator("rect")
      .getAttribute("fill");
  const wide = await widthOf("HighCPU on web-01"); // 150 min span
  const narrow = await widthOf("DiskSlow on edge-01"); // 15 min span
  assert(wide > narrow * 3, `duration sizing: HighCPU ${wide}px vs DiskSlow ${narrow}px`);
  assert((await fillOf("HighCPU on web-01")) === "#ef4444", "critical pill is red");
  assert((await fillOf("SlowQueries on db-01")) === "#f59e0b", "warning pill is amber");
  assert((await fillOf("DiskSlow on edge-01")) === "#3b82f6", "info pill is blue");
  log(`pill widths/fills correct (HighCPU ${wide}px > DiskSlow ${narrow}px)`);

  // 4. temporal arcs exist (burst incidents within correlation window)
  const arcs = await page.locator('path[stroke="#22d3ee"]').count();
  assert(arcs >= 3, `expected >=3 temporal arcs, got ${arcs}`);
  log(`${arcs} temporal arcs drawn`);

  // 5. hover PacketLoss pill -> same_name dashed arc + partner highlight
  await page
    .locator('g[data-testid="incident-pill"]:has-text("PacketLoss on web-01")')
    .hover();
  await page.waitForSelector('[data-testid="same-name-arc"]');
  const sameNameArcs = await page.locator('[data-testid="same-name-arc"]').count();
  assert(sameNameArcs >= 1, "same_name arc appears on hover");
  await page.screenshot({ path: SHOT("g2-hover-same-name") });
  log(`hover -> ${sameNameArcs} same_name arc(s) shown`);

  // arcs disappear when hover ends
  await page.mouse.move(5, 5);
  await sleep(300);
  assert(
    (await page.locator('[data-testid="same-name-arc"]').count()) === 0,
    "same_name arcs hidden after hover ends",
  );
  log("same_name arcs hidden after unhover");

  // 6. click incident -> side panel with member alerts from /graph/incident/{id}
  await page
    .locator('g[data-testid="incident-pill"]:has-text("PacketLoss on web-01")')
    .click();
  await page.waitForSelector('[data-testid="graph-detail"]');
  await page.waitForSelector('[data-testid="graph-detail"] :text("구성 알림")');
  await page.waitForSelector('[data-testid="graph-detail"] :text("alertmanager")');
  const memberRows = await page
    .locator('[data-testid="graph-detail"] .max-h-44 > div')
    .count();
  assert(memberRows === 2, `expected 2 member alerts, got ${memberRows}`);
  await page.screenshot({ path: SHOT("g3-incident-panel") });
  log(`incident panel shows ${memberRows} member alerts`);
  await page.locator('[data-testid="swimlane-chart"]').click({ position: { x: 400, y: 700 } });
  await sleep(300);

  // 7. lane overflow expander: +2 hosts -> 14 lanes -> collapse back
  const expander = page.locator('[data-testid="lane-expander"]');
  await expander.scrollIntoViewIfNeeded();
  const expanderText = await expander.textContent();
  assert(expanderText.includes("2"), `expander shows hidden count: "${expanderText}"`);
  await expander.click();
  await page.waitForSelector('[data-testid="lane-collapse"]');
  const expandedLanes = await page.locator('g[data-testid^="lane-"]').count();
  assert(expandedLanes === 14, `expected 14 lanes expanded, got ${expandedLanes}`);
  await page.screenshot({ path: SHOT("g4-lanes-expanded") });
  log(`expander "+2 hosts" -> ${expandedLanes} lanes`);
  await page.locator('[data-testid="lane-collapse"]').click();
  await sleep(300);
  assert(
    (await page.locator('g[data-testid^="lane-"]').count()) === 12,
    "collapse restores lane cap",
  );
  log("collapse back to 12 lanes");

  // 8. manual refresh refetches /graph
  const refetch = page.waitForResponse((r) => r.url().includes("/api/v1/graph?"));
  await page.click('[data-testid="graph-refresh"]');
  const resp = await refetch;
  assert(resp.ok(), `refresh refetch status ${resp.status()}`);
  await page.waitForSelector('[data-testid="incident-pill"]');
  log("manual refresh refetched /graph OK");

  console.log("GRAPH_E2E_OK");
} catch (err) {
  await page.screenshot({ path: SHOT("99-graph-failure") });
  console.error("FAILED:", err.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
