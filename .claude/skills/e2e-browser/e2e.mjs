import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";

const BASE = "http://127.0.0.1:5173";
const SHOT = (n) => `/tmp/shots/${n}.png`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1380, height: 860 } });
page.setDefaultTimeout(15000);

const log = (m) => console.log("STEP:", m);

async function closeOverlays() {
  for (let i = 0; i < 20; i++) {
    const n = await page.locator('div[aria-hidden="true"][data-state="open"]').count();
    if (n === 0) return;
    await page.keyboard.press("Escape");
    await sleep(200);
  }
}

try {
  // 1. login page
  await page.goto(BASE + "/login");
  await page.waitForSelector("text=Atlas");
  await page.screenshot({ path: SHOT("01-login") });
  log("login page rendered");

  // probe: wrong password
  await page.fill("#email", "admin@example.com");
  await page.fill("#password", "wrong-password");
  await page.click('button[type="submit"]');
  await page.waitForSelector("text=로그인에 실패했습니다");
  await page.screenshot({ path: SHOT("02-login-fail-toast") });
  log("wrong password -> failure toast shown");

  // real login
  await page.fill("#password", "password123");
  await page.click('button[type="submit"]');
  await page.waitForURL(BASE + "/");
  await page.waitForSelector("text=대시보드");
  await sleep(800);
  await page.screenshot({ path: SHOT("03-dashboard") });
  log("logged in, dashboard rendered");

  // 2. servers: create one
  await page.click('a[href="/servers"]');
  await page.waitForSelector("h1:has-text('서버')");
  await page.click("button:has-text('생성')");
  await page.fill("#s-name", "web-01");
  await page.fill("#s-desc", "프론트엔드 웹 서버");
  await page.fill("#s-labels", '{"job": "node", "env": "prod"}');
  await page.screenshot({ path: SHOT("04-server-form") });
  await page.click("button:has-text('저장')");
  await page.waitForSelector("td:has-text('web-01')");
  await page.screenshot({ path: SHOT("05-servers-list") });
  await closeOverlays();
  log("server web-01 created and listed");

  // 3. rules: create a global rule
  await page.click('a[href="/rules"]');
  await page.waitForSelector("h1:has-text('알림 룰')");
  await page.click("button:has-text('룰 생성')");
  await page.waitForSelector("text=지속 시간");
  await page.fill("#name", "HighCPUUsage");
  await page.fill("#for_duration", "5m");
  // monaco editor: click and type
  await page.click(".monaco-editor");
  await page.keyboard.type('avg(rate(node_cpu_seconds_total{mode!="idle"}[5m])) > 0.9');
  await page.fill('textarea[placeholder*="team"]', '{"team": "infra"}');
  await page.fill('textarea[placeholder*="summary"]', '{"summary": "CPU 90% 초과"}');
  await page.screenshot({ path: SHOT("06-rule-form") });
  await page.click("#rule-form ~ * button:has-text('저장'), button[form='rule-form']");
  await page.waitForSelector("td:has-text('HighCPUUsage')");
  await page.screenshot({ path: SHOT("07-rules-list") });
  await closeOverlays();
  log("rule HighCPUUsage created and listed");

  // 4. open rule, validate
  await page.click("td:has-text('HighCPUUsage')");
  await page.waitForSelector("button:has-text('검증')");
  await page.click("button:has-text('검증')");
  await page.waitForSelector("text=문법 검증 통과");
  await page.screenshot({ path: SHOT("08-rule-validate") });
  log("validate -> 문법 검증 통과 toast");
  await page.keyboard.press("Escape");
  await closeOverlays();

  // 5. emergency apply via row menu
  const row = page.locator("tr", { hasText: "HighCPUUsage" });
  await row.locator("button").last().click();
  await page.click("text=긴급 적용");
  await page.waitForSelector("text=계속하시겠습니까");
  // probe: confirm without reason
  await page.click("div[role=dialog] button:has-text('긴급 적용')");
  await page.waitForSelector("text=긴급 적용 사유");
  await page.screenshot({ path: SHOT("09-emergency-no-reason") });
  log("emergency apply without reason -> blocked with toast");
  await page.fill("div[role=dialog] textarea", "운영 장애 #123 — CPU 알람 즉시 필요");
  await page.screenshot({ path: SHOT("10-emergency-dialog") });
  await page.click("div[role=dialog] button:has-text('긴급 적용')");
  await page.waitForSelector("text=성공");
  await page.screenshot({ path: SHOT("11-emergency-applied") });
  await closeOverlays();
  log("emergency apply with reason -> success toast");

  // 6. server detail shows global rule
  await page.click('a[href="/servers"]');
  await page.click("td:has-text('web-01')");
  await page.waitForSelector("h1:has-text('web-01')");
  await page.waitForSelector("text=HighCPUUsage");
  await page.screenshot({ path: SHOT("12-server-detail") });
  log("server detail shows applied global rule");

  // 7. audit log with emergency entry
  await page.click('a[href="/audit"]');
  await page.waitForSelector("h1:has-text('감사 로그')");
  await page.waitForSelector("text=emergency_apply");
  await page.screenshot({ path: SHOT("13-audit-list") });
  await page.click("td:has-text('emergency_apply')");
  await page.waitForSelector("text=After");
  await page.screenshot({ path: SHOT("14-audit-detail") });
  log("audit log shows emergency_apply with before/after detail");
  await page.keyboard.press("Escape");
  await closeOverlays();

  // 8. probe: dark mode toggle
  await page.click("button:has(svg.lucide-sun)");
  await page.click("text=다크");
  await sleep(400);
  await page.screenshot({ path: SHOT("15-dark-mode") });
  log("dark mode applied");

  // 9. probe: mobile viewport (sidebar -> sheet)
  await page.setViewportSize({ width: 390, height: 844 });
  await sleep(300);
  await page.click("header button:has(svg.lucide-menu)");
  await sleep(500);
  await page.screenshot({ path: SHOT("16-mobile-sheet") });
  log("mobile sheet navigation opens");

  console.log("E2E_OK");
} catch (e) {
  await page.screenshot({ path: SHOT("99-failure") }).catch(() => {});
  console.error("E2E_FAIL:", e.message);
  process.exitCode = 1;
} finally {
  await browser.close();
}
