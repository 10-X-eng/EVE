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
      const script = {id:'python-test', role:'tool', text:'', title:'Create <bracket>',
        code:'def run(context):\n' + '    # <script>alert(1)</script>\n'.repeat(40), toolStatus:'running'};
      snapshot.messages.push(script); snapshot.busy = true; snapshot.status = 'Working in Fusion';
      send(); await frame();
      const card = conversation.lastChild.querySelector('details');
      const codePane = card.querySelector('pre');
      const scriptText = card.querySelector('code').firstChild;
      check(card.open && codePane.clientHeight <= 210, 'Live code must open in a bounded pane');
      check(card.querySelector('code').textContent === script.code && !card.querySelector('script'), 'Python was parsed as markup');
      codePane.scrollTop = 40; card.open = false;
      snapshot.waitingForFusion = true;
      send(); await frame();
      check(card.querySelector('.code-meta').textContent.startsWith('Waiting for Fusion'), 'Missing waiting state');
      check(!card.open && card.querySelector('code').firstChild === scriptText, 'State update rebuilt or reopened code');
      card.open = true; codePane.scrollTop = 40;
      const codeScroll = codePane.scrollTop;
      script.toolStatus = 'completed'; snapshot.waitingForFusion = false;
      send(); await frame();
      check(card.querySelector('.code-meta').textContent.startsWith('Completed'), 'Missing completion state');
      check(codePane.scrollTop === codeScroll && card.querySelector('code').firstChild === scriptText, 'Completion reset code scroll or selection');
      script.toolStatus = 'failed'; send(); await frame();
      check(card.dataset.status === 'failed', 'Missing failure state');
      script.toolStatus = 'unconfirmed'; send(); await frame();
      check(card.querySelector('.code-meta').textContent.startsWith('Completion unconfirmed'), 'Interrupted script falsely marked complete');
      snapshot.messages.push({...script, id:'historical-code', historical:true}); send(); await frame();
      check(!conversation.lastChild.querySelector('details').open, 'Saved code should start collapsed');
      const goalCalls = [];
      window.adsk.fusionSendData = async (action, payload) => {goalCalls.push({action, payload:JSON.parse(payload)});return '{"ok":true}';};
      snapshot.goal = {objective:'Build <fixture> and verify dimensions',status:'active',tokensUsed:1250,tokenBudget:50000,timeUsedSeconds:125};
      snapshot.canSteer = false; snapshot.goalHasTarget = true;
      send(); await frame();
      check(!document.getElementById('goal-strip').hidden, 'Goal status hidden');
      document.getElementById('goal-button').click();
      check(document.getElementById('goal-dialog').open, 'Goal controls did not open');
      check(document.getElementById('goal-save').disabled, 'Editing a running goal should require pausing');
      check(document.getElementById('goal-summary').textContent.includes('<fixture>') && !document.querySelector('fixture'), 'Unsafe goal rendering');
      document.getElementById('goal-pause').click(); await frame();
      check(goalCalls.some(c=>c.action==='goal' && c.payload.command==='pause'), 'Pause was sent as model text');
      snapshot.busy=false; snapshot.goal.status='paused'; send(); await frame();
      document.getElementById('goal-budget').value='70000';
      document.getElementById('goal-resume').click(); await frame();
      check(goalCalls.at(-1).payload.command==='resume' && goalCalls.at(-1).payload.tokenBudget===70000, 'Resume lost budget');
      document.getElementById('goal-strip').click();
      document.getElementById('goal-objective').value='Verify revised bracket';
      document.getElementById('goal-budget').value='';
      document.getElementById('goal-form').requestSubmit(); await frame();
      check(goalCalls.at(-1).payload.command==='set' && goalCalls.at(-1).payload.tokenBudget===null, 'Goal editor did not submit');
      document.getElementById('message').value='/goal edit';
      document.getElementById('composer').requestSubmit(); await frame();
      check(document.getElementById('goal-dialog').open && document.getElementById('goal-objective').value===snapshot.goal.objective, 'Slash edit did not open existing objective');
      document.getElementById('goal-close').click();
      snapshot.busy=true; snapshot.goal.status='active'; send(); await frame();
      document.getElementById('message').value='/goal clear';
      document.getElementById('message').dispatchEvent(new Event('input'));
      check(!document.getElementById('send').disabled, 'Goal command unavailable between automatic turns');
      document.getElementById('composer').requestSubmit(); await frame();
      check(goalCalls.at(-1).payload.text==='/goal clear', 'Slash clear did not reach controller command parser');
      snapshot.codexVersion='0.155.1'; snapshot.codexUpdateInfo={version:'99.0.0'};
      snapshot.codexUpdateStatus='Codex 99.0.0 is available'; send(); await frame();
      check(document.getElementById('codex-version').textContent==='Codex 0.155.1', 'Runtime version missing');
      check(!document.getElementById('update-codex').disabled, 'Background download blocked by active turn');
      document.getElementById('update-codex').click(); await frame();
      check(goalCalls.at(-1).action==='updateCodex', 'Codex update did not reach controller');
      snapshot.codexUpdating=true; send(); await frame();
      check(document.getElementById('update-codex').disabled, 'Duplicate update not disabled');
      snapshot.codexUpdating=false; snapshot.codexPendingVersion='99.0.0'; send(); await frame();
      check(document.getElementById('codex-update-status').textContent.includes('Restart STEVE'), 'Missing restart instruction');
      check(document.getElementById('update-codex').hidden, 'Pending update offered twice');
      check(!document.getElementById('bundled-codex').hidden, 'Recovery control missing');
      check(document.getElementById('restart-steve').disabled, 'Restart should not interrupt an active task');
      snapshot.busy=false; snapshot.goal=null; send(); await frame();
      document.getElementById('restart-steve').click(); await frame();
      check(goalCalls.at(-1).action==='restartRuntime', 'Restart did not reach controller');
      snapshot.codexRestarting=true; send(); await frame();
      check(document.getElementById('restart-steve').disabled && document.getElementById('send').disabled, 'Restart should block duplicate restarts and new turns');
      snapshot.codexRestarting=false; send(); await frame();
      document.getElementById('chatgpt-refresh').click(); await frame();
      check(goalCalls.at(-1).action==='accountRefresh' && goalCalls.at(-1).payload.refreshModels, 'Model refresh missing');
      return {tokenUpdates: 240, domMutations: mutations.length, messagesRetained: articles.length};
};


(async () => {
  if (process.argv.includes('--fixture')) {
    const fs = require('node:fs');
    const root = path.resolve(__dirname, '..');
    const cache = path.join(root, '.cache');
    fs.mkdirSync(cache, {recursive: true});
    const html = fs.readFileSync(path.join(root, 'addin/STEVE/panel/index.html'), 'utf8')
      .replace(/(src|href)="(?![a-z]+:|\/|#)([^"]+)"/g, '$1="/addin/STEVE/panel/$2"')
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
    await page.goto(pathToFileURL(path.resolve(__dirname, '../addin/STEVE/panel/index.html')).href);
    await page.waitForFunction(() => !!window.fusionJavaScriptHandler);
    const results = await page.evaluate(runChecks);
    assert.deepEqual(errors, []);
    console.log('Streaming DOM checks passed:', results);
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
