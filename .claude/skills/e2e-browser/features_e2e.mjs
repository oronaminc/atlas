/** Features A+B e2e: top-bar search dropdown -> route into /ops; LLM Analyze
 *  -> result rendered. Prereqs (see header curl prep in session): backend+
 *  frontend up, an OpenAI-compatible stub at :18090, llm-config enabled to it,
 *  2 correlated incidents (db-01/web-01), llm_worker running. */
import { chromium } from "/opt/node22/lib/node_modules/playwright/index.mjs";
const BASE = "http://127.0.0.1:5173";
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1380, height: 950 } });
p.setDefaultTimeout(15000);
const assert = (c, m) => { if (!c) throw new Error("ASSERT: " + m); };
try {
  await p.goto(BASE + "/login");
  await p.fill("#email", "admin@example.com");
  await p.fill("#password", "password123");
  await p.click('button[type="submit"]');
  await p.waitForURL(BASE + "/");
  await p.waitForSelector('[data-testid="global-search"]');
  await p.fill('[data-testid="search-input"]', "db-01");
  await p.waitForSelector('[data-testid="search-result-host"]');
  await p.selectOption('[data-testid="search-type"]', "text");
  await p.fill('[data-testid="search-input"]', "DiskFull");
  await p.waitForSelector('[data-testid="search-result-text"]');
  await p.click('[data-testid="search-result-text"]');
  await p.waitForURL(/\/ops\?incident=/);
  await p.waitForSelector('[data-testid="analyze-button"]');
  await p.click('[data-testid="analyze-button"]');
  await p.waitForSelector('[data-testid="analysis-done"]', { timeout: 20000 });
  const txt = await p.locator('[data-testid="analysis-done"]').textContent();
  assert(/disk/i.test(txt), "analysis rendered");
  console.log("FEATURES_E2E_OK");
} catch (e) { console.error("FAILED:", e.message); process.exitCode = 1; }
finally { await b.close(); }
