// Real browser coverage for the embedded header menus. Requires Playwright and Edge.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 436, height: 626}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.testActions = [];
      window.adsk = {fusionSendData: async (action, payload) => {
        window.testActions.push({action, payload});
        return '{"ok":true}';
      }};
    });
    await page.goto(pathToFileURL(path.resolve(__dirname, '../addin/STEVE/panel/index.html')).href);
    const snapshot = {connection: 'ready', account: {email: 'designer@example.com', planType: 'Plus'},
      accountChecked: true, models: [], messages: [], busy: false, status: 'Ready', version: '0.6.2',
      codexVersion: '0.155.1', codexPendingVersion: '0.155.2', dfmEnabled: true, rmfgState: 'connected'};
    const send = async patch => {
      Object.assign(snapshot, patch);
      await page.evaluate(snapshot => window.fusionJavaScriptHandler.handle('state', JSON.stringify(snapshot)), snapshot);
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)));
    };
    await send({});
    await page.locator('#app-menu-button').focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#app-menu').isVisible(), true);
    assert.equal(await page.locator('#app-menu-button').getAttribute('aria-expanded'), 'true');
    assert.equal(await page.locator('#updates-settings').getAttribute('open'), null);
    assert.equal(await page.locator('#updates-badge').textContent(), 'Restart ready');
    assert.equal(await page.locator('#restart-steve').isVisible(), true);
    assert.equal(await page.locator('#account-menu').isVisible(), false);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    assert.equal(await page.locator('#app-menu-button').evaluate(el => el === document.activeElement), true);

    await page.locator('#app-menu-button').click();
    await page.locator('#updates-settings > summary').click();
    await page.locator('#check-codex-updates').click();
    assert.equal(await page.locator('#app-menu').isVisible(), true);
    await page.locator('#app-menu .settings-group').nth(1).locator('summary').click();
    await page.locator('#debug-logging').check();
    await page.locator('#open-logs').click();
    await page.locator('#dfm-enabled').uncheck();
    const actions = await page.evaluate(() => window.testActions);
    for(const name of ['checkCodexUpdates', 'debugLogging', 'openLogs', 'dfm'])
      assert(actions.some(entry => entry.action === name), `Missing bridge action ${name}`);
    await send({busy: true});
    assert.equal(await page.locator('#restart-steve').isDisabled(), true);
    assert.equal(await page.locator('#dfm-enabled').isDisabled(), true);
    await page.keyboard.press('Escape');
    await page.locator('#updates-settings').evaluate(el => el.open = false);
    await page.locator('#app-menu .settings-group').nth(1).evaluate(el => el.open = false);
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('#updates-settings > summary').evaluate(el => el === document.activeElement), true);
    await send({busy: false});

    await page.locator('#account-button').click();
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    assert.equal(await page.locator('#account-menu').isVisible(), true);
    assert.equal(await page.locator('#app-menu-button').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.locator('#provider').isVisible(), true);
    await page.locator('#rmfg-settings > summary').click();
    assert.equal(await page.locator('#rmfg-disconnect').isVisible(), true);
    assert.equal(await page.locator('#rmfg-enable-checkout').isVisible(), true);
    await page.locator('#rmfg-enable-checkout').click();
    assert.equal(await page.evaluate(() => window.testActions.at(-1).action), 'rmfgEnableCheckout');
    await send({rmfgCheckoutEnabled: true});
    assert.equal(await page.locator('#rmfg-enable-checkout').isVisible(), false);
    await page.locator('#history-button').click();
    assert.equal(await page.locator('#account-menu').isVisible(), false);
    assert.equal(await page.locator('#history-panel').isVisible(), true);
    await page.locator('#app-menu-button').click();
    assert.equal(await page.locator('#history-panel').isVisible(), false);
    await page.locator('#app-menu-button').click();
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    await page.locator('#app-menu-button').click();
    await page.mouse.click(4, 300);
    assert.equal(await page.locator('#app-menu').isVisible(), false);
    await page.locator('#account-button').click();
    await page.locator('#message').focus();
    assert.equal(await page.locator('#account-menu').isVisible(), false);
    await send({threadId: 'fixture-chat', rmfgCheckout: {id: 'receipt-1', threadId: 'fixture-chat'}});
    assert.equal(await page.locator('#rmfg-checkout').isVisible(), true);
    await page.locator('#rmfg-open-checkout').click();
    const checkoutAction = await page.evaluate(() => window.testActions.find(entry => entry.action === 'rmfgOpenCheckout'));
    assert.deepEqual(JSON.parse(checkoutAction.payload), {checkoutId: 'receipt-1'});
    await send({threadId: 'other-chat'});
    assert.equal(await page.locator('#rmfg-checkout').isVisible(), false);
    await send({rmfgCheckout: null});

    // Keep both expanded panels reachable in a narrow, short Fusion palette.
    for (const width of [320, 436, 760]) {
      await page.setViewportSize({width, height: 480});
      for (const id of ['app-menu', 'account-menu']) {
        await page.locator(id === 'app-menu' ? '#app-menu-button' : '#account-button').click();
        const bounds = await page.locator('#' + id).boundingBox();
        assert(bounds.x >= 0 && bounds.x + bounds.width <= width && bounds.y + bounds.height <= 480);
        assert(await page.locator('#' + id).evaluate(el => el.scrollWidth <= el.clientWidth));
        const brand = await page.locator('#app-menu-button').boundingBox();
        const history = await page.locator('#history-button').boundingBox();
        assert(brand.x + brand.width <= history.x, 'Header controls overlap');
        await page.keyboard.press('Escape');
      }
    }
    await page.setViewportSize({width: 436, height: 626});
    await page.locator('#updates-settings').evaluate(el => el.open = false);
    await page.locator('#app-menu .settings-group').nth(1).evaluate(el => el.open = false);
    await page.locator('#app-menu-button').click();
    if(process.env.STEVE_MENU_SCREENSHOT) await page.screenshot({path: process.env.STEVE_MENU_SCREENSHOT});
    assert.deepEqual(errors, []);
    console.log('Menu checks passed: keyboard/focus, dismissal, exclusive panels, actions, busy guards and responsive layout.');
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
