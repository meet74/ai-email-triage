// Screenshots for the README. Usage:
//   node scripts/screenshots.js approval            renders assets/approval-message.html
//   node scripts/screenshots.js canvas <base-url>   workflow canvases from a running n8n
//   node scripts/screenshots.js cover               renders assets/cover.html
const { chromium } = require('playwright');
const path = require('path');
const root = path.resolve(__dirname, '..');

async function shoot(url, out, w, h, setup) {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
  if (setup) await setup(page);
  else await page.goto(url);
  await page.waitForTimeout(500);
  await page.screenshot({ path: out });
  await browser.close();
}

async function canvas(base) {
  const owner = { emailOrLdapLoginId: 'owner@example.com', password: 'Demo-pass-1234' };
  const targets = [
    ['NbTriage0000001', 'n8n-inbox-triage.png', 1600, 900],
    ['NbApprove000001', 'n8n-approval-handler.png', 1600, 800],
  ];
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 900 } });
  const login = await ctx.request.post(`${base}/rest/login`, { data: owner });
  if (!login.ok()) throw new Error('login failed: ' + login.status());
  for (const [id, file, w, h] of targets) {
    const page = await ctx.newPage();
    await page.setViewportSize({ width: w, height: h });
    await page.goto(`${base}/workflow/${id}`);
    await page.waitForSelector('.vue-flow__node', { timeout: 60000 });
    await page.waitForTimeout(2500);
    // dismiss any modal and fit the graph to the viewport
    await page.keyboard.press('Escape');
    await page.mouse.click(w / 2, h - 40);
    await page.keyboard.press('Shift+1');
    await page.waitForTimeout(1200);
    await page.screenshot({ path: path.join(root, 'assets', file) });
    console.log('wrote assets/' + file);
    await page.close();
  }
  await browser.close();
}

(async () => {
  const [mode, arg] = process.argv.slice(2);
  if (mode === 'approval') await shoot('file://' + path.join(root, 'assets', 'approval-message.html'), path.join(root, 'assets', 'approval-message.png'), 760, 690);
  else if (mode === 'cover') await shoot('file://' + path.join(root, 'assets', 'cover.html'), path.join(root, 'assets', 'cover.png'), 1600, 1200);
  else if (mode === 'canvas') await canvas(arg);
  else { console.error('usage: screenshots.js approval|cover|canvas <url>'); process.exit(2); }
})();
