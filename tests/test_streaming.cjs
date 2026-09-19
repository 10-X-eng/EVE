// Real DOM regression checks. Requires Playwright and an installed Edge browser.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const runChecks = async () => {
      const check = (value, message) => { if (!value) throw new Error(message); };
      const frame = () => new Promise(resolve => requestAnimationFrame(resolve));
      const messages = [
        {role: 'user', text: 'Explain sketches'},
        {id: 'previous', role: 'assistant', text: 'An earlier answer.\n\n' + 'A paragraph about constraints.\n\n'.repeat(30)},
        {role: 'user', text: 'Show code'},
        {id: 'current', role: 'assistant', text: 'Keep this paragraph.\n\n```python\n' + 'some_long_example = 1234567890; '.repeat(12)},
      ];
      const snapshot = {connection: 'ready', account: {email: 'fixture@example.com', planType: 'Plus'},
        accountChecked: true, models: [], model: '', messages, busy: true,
        loginPending: false, status: 'Writing', error: ''};
      const send = () => check(window.fusionJavaScriptHandler.handle('state', JSON.stringify(snapshot)) === 'OK', 'Bridge rejected snapshot');
      send(); await frame();
      const conversation = document.getElementById('conversation');
      const scroll = document.getElementById('scroll-area');
      const articles = Array.from(conversation.children);
      const active = articles[3].querySelector('.message-body');
      const paragraph = active.firstChild;
      const code = active.querySelector('code');
      const text = code.firstChild;
      const pre = active.querySelector('pre');
      pre.scrollLeft = 60;
      scroll.scrollTop = 120;
      const oldTop = scroll.scrollTop;
      const range = document.createRange();
      range.selectNodeContents(articles[1].querySelector('p'));
      const selection = getSelection(); selection.removeAllRanges(); selection.addRange(range);
      const selected = selection.toString();
      const mutations = [];
      const observer = new MutationObserver(records => mutations.push(...records));
      observer.observe(document.getElementById('app'), {subtree: true, childList: true, characterData: true, attributes: true});
      // Bursts from the bridge should produce one text append per animation frame.
      for (let batch = 0; batch < 12; batch++) {
        for (let token = 0; token < 20; token++) { messages[3].text += 'x'; send(); }
        await frame();
      }
      await Promise.resolve();
      observer.disconnect();
      check(articles.every((article, index) => conversation.children[index] === article), 'Existing message was replaced');
      check(active.firstChild === paragraph && code.firstChild === text, 'Existing Markdown/text nodes were replaced');
      check(text.data.endsWith('x'.repeat(240)), 'Stream lost tokens');
      check(pre.scrollLeft === 60, 'Code block horizontal scroll was reset');
      check(scroll.scrollTop === oldTop, 'Streaming stole the reader scroll position');
      check(selection.toString() === selected, 'Streaming discarded text selection');
      check(mutations.length === 12 && mutations.every(record => record.type === 'characterData' && record.target === text),
        `Expected 12 text appends only; got ${mutations.length} mutations`);
      scroll.scrollTop = scroll.scrollHeight;
      messages[3].text += '\n```\n\n## Next\n\n' + 'Another paragraph.\n\n'.repeat(8);
      send(); await frame();
      check(scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 2, 'Bottom-follow lost the latest text');
      check(active.querySelector('pre') === pre, 'Closing a fence replaced the code block');
      // Final corrected content and a stopped turn must render, not get lost to batching.
      messages[3].text = '**Final** answer with `<script>` as text.';
      snapshot.busy = false; snapshot.status = 'Stopped'; send(); await frame();
      check(active.querySelector('strong').textContent === 'Final', 'Final Markdown missing');
      check(!active.querySelector('script'), 'Model text became executable markup');
      check(document.getElementById('stop').hidden, 'Stop button did not reset');
      check(document.getElementById('status').textContent === 'Stopped', 'Terminal status missing');
      snapshot.messages = []; send(); await frame();
      check(conversation.children.length === 0 && scroll.scrollTop === 0, 'New chat retained old messages or scroll');
      snapshot.messages = [{role: 'user', text: 'Fresh chat'}, {id: 'fresh', role: 'assistant', text: '- **First**\n- Second'}];
      send(); await frame();
      check(conversation.children.length === 2 && conversation.querySelectorAll('li').length === 2, 'New chat did not render');
      return {tokenUpdates: 240, domMutations: mutations.length, messagesRetained: articles.length};
};


(async () => {
  if (process.argv.includes('--fixture')) {
    const fs = require('node:fs');
    const root = path.resolve(__dirname, '..');
    const cache = path.join(root, '.cache');
    fs.mkdirSync(cache, {recursive: true});
    const html = fs.readFileSync(path.join(root, 'addin/EVE/panel/index.html'), 'utf8')
      .replace(/(src|href)="(?![a-z]+:|\/|#)([^"]+)"/g, '$1="/addin/EVE/panel/$2"')
      .replace('<head>', '<head><script src="/.cache/streaming-bridge.js"></script>')
      .replace('</head>', '<script src="/.cache/streaming-check.js" defer></script></head>');
    fs.writeFileSync(path.join(cache, 'streaming-check.html'), html);
    fs.writeFileSync(path.join(cache, 'streaming-bridge.js'), 'window.adsk={fusionSendData:async()=>JSON.stringify({ok:true})};');
    fs.writeFileSync(path.join(cache, 'streaming-check.js'), `(${runChecks.toString()})().then(result => {
      const output = document.createElement('pre'); output.id = 'test-result';
      output.style = 'position:fixed;inset:0;z-index:100;background:#151a1d;color:#b5dfcc;padding:24px;white-space:pre-wrap';
      output.textContent = 'PASS: ' + JSON.stringify(result); document.body.appendChild(output);
    }).catch(error => {
      const output = document.createElement('pre'); output.id = 'test-result';
      output.textContent = 'FAIL: ' + error.message; document.body.prepend(output);
    });`);
    console.log('Serve the repository root and open /.cache/streaming-check.html');
    return;
  }
  const {chromium} = require('playwright');
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 436, height: 626}});
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.addInitScript(() => {
      window.adsk = {fusionSendData: async () => '{"ok":true}'};
    });
    await page.goto(pathToFileURL(path.resolve(__dirname, '../addin/EVE/panel/index.html')).href);
    await page.waitForFunction(() => !!window.fusionJavaScriptHandler);
    const results = await page.evaluate(runChecks);
    assert.deepEqual(errors, []);
    console.log('Streaming DOM checks passed:', results);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
