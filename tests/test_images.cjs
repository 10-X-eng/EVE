const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../addin/EVE/panel');
const png = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII=';
const elements = new Map();
function element() {
  return {value:'', hidden:false, children:[], attrs:{}, style:{},
    append(...items){this.children.push(...items);},
    replaceChildren(...items){this.children=items;},
    insertBefore(item){this.children.push(item);},
    setAttribute(key,value){this.attrs[key]=value;}, focus(){}, click(){},
    showModal(){this.open=true;}, close(){this.open=false;}, removeAttribute(key){delete this[key];}};
}
const context = {URLSearchParams, File:require('node:buffer').File, atob, Uint8Array, setTimeout, clearTimeout, location:{search:''}, window:{},
  document:{getElementById(id){if(!elements.has(id))elements.set(id,element());return elements.get(id);},createElement:element},
  requestAnimationFrame:()=>1};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root,'images.js'),'utf8'),context);
const images = vm.runInContext('EveImages',context);
const file={name:'Screenshot.png',type:'image/png',size:100};
assert.equal(images.clipboardFile({url:png}).type,'image/png');
assert.throws(()=>images.clipboardFile({url:'https://example.com/image.png'}),/supported image/);
for(const url of ['https://example.com/private.png','data:image/svg+xml;base64,PHN2Zz4=','data:image/png;base64,bad"'])assert.equal(images.imageURL(url),false);
assert.equal(images.imageURL(png),true);
const source=fs.readFileSync(path.join(root,'panel.js'),'utf8');
vm.runInContext(source.slice(0,source.indexOf('$("login").onclick')),context);
vm.runInContext(`render=()=>{};resize=()=>{};
  state={account:{},connection:'ready',busy:false,threadId:'thread',turnId:'turn'};
  let requests=[];bridge=async(action,payload)=>{requests.push({action,payload});return {ok:true};};`,context);
vm.runInContext(source.slice(source.indexOf('$("message").onpaste'),source.indexOf('// Explicit design preview')),context);
const run=code=>vm.runInContext(code,context);
const submit=()=>elements.get('composer').onsubmit({preventDefault(){}});
(async()=>{
  await assert.rejects(images.prepare({...file,type:'image/svg+xml'}),/PNG/);
  await assert.rejects(images.prepare({...file,size:21*1024*1024}),/20 MiB/);
  let preparation;
  images.prepare=()=>new Promise(resolve=>{preparation=resolve;});
  const attach=context.attachImages([file]);
  await submit();assert.equal(run('requests.length'),0,'Cannot send while image decode is pending');
  assert.equal(run('draftImages.length'),1);
  preparation({name:file.name,url:png});await attach;
  await submit();
  assert.equal(run('requests[0].action'),'send');
  assert.equal(run('requests[0].payload.text'),'');
  assert.equal(run('requests[0].payload.images[0].url'),png);
  assert.equal(run('draftImages.length'),0);
  images.prepare=async()=>({name:file.name,url:png});
  await context.attachImages([file]);
  run(`state.busy=true;state.canSteer=true;bridge=async()=>{throw new Error('Disconnected');};`);
  await submit();assert.equal(run('draftImages.length'),1,'Failed bridge retains attachment');
  assert.equal(run('state.error'),'Disconnected');
  run(`bridge=async(action,payload)=>{requests.push({action,payload});return {ok:true};};`);
  await submit();assert.equal(run('requests[1].action'),'steer');
  assert.equal(run('requests[1].payload.turnId'),'turn');
  await context.attachImages([file,file,file,file,file]);assert.equal(run('draftImages.length'),0);
  assert.match(run('state.error'),/four/);
  let prevented=false;
  elements.get('message').onpaste({clipboardData:{items:[{kind:'string',type:'text/plain'}]},preventDefault(){prevented=true;}});
  assert.equal(prevented,false,'Ordinary text paste remains native');
  const beforePaste=run('requests.length');
  elements.get('message').onpaste({clipboardData:{items:[],types:[]},preventDefault(){prevented=true;}});
  assert.equal(prevented,true,'An image paste is handled even when Qt exposes no browser File');
  assert.equal(run('requests.length'),beforePaste+1);
  assert.equal(run('requests.at(-1).action'),'clipboardImage');
  const pasteId=run('requests.at(-1).payload.requestId');
  elements.get('message').value='Do not send before paste completes';
  await submit();assert.equal(run('requests.length'),beforePaste+1,'Pending native image blocks submit');
  await context.finishClipboardImage({requestId:'stale',image:{url:png}});
  assert.equal(run('draftImages.length'),0);
  await context.finishClipboardImage({requestId:pasteId,image:{url:png}});
  assert.equal(run('draftImages.length'),1,'Native screenshot uses normal attachment preparation');
  await context.finishClipboardImage({requestId:pasteId,image:{url:png}});
  assert.equal(run('draftImages.length'),1,'Duplicate response cannot attach twice');
  elements.get('image-drafts').children[0].children[1].onclick();
  context.pasteClipboardImage();
  const staleId=run('requests.at(-1).payload.requestId');
  run("state.threadId='other-thread';");
  await context.finishClipboardImage({requestId:staleId,image:{url:png}});
  assert.equal(run('draftImages.length'),0,'Paste cannot arrive in another conversation');
  run("state.threadId='thread';");
  context.pasteClipboardImage();
  await context.finishClipboardImage({requestId:run('requests.at(-1).payload.requestId'),error:'Clipboard unavailable'});
  assert.equal(run('clipboardRequest'),null);
  assert.equal(run('state.error'),'Clipboard unavailable');
  assert.equal(elements.get('message').value,'Do not send before paste completes','Paste errors preserve text');
  const beforeSynthetic=run('requests.length');
  elements.get('message').onpaste({isTrusted:false,preventDefault(){}});
  assert.equal(run('requests.length'),beforeSynthetic,'Synthetic events cannot read the clipboard');
  // Removing a thumbnail while decode is pending must not resurrect it.
  images.prepare=()=>new Promise(resolve=>{preparation=resolve;});
  const pending=context.attachImages([file]);
  elements.get('image-drafts').children[0].children[1].onclick();
  preparation({name:file.name,url:png});await pending;
  assert.equal(run('draftImages.length'),0);
  // State notifications cannot unlock a submit that's awaiting bridge acceptance.
  let accepted;
  context.hold=()=>new Promise(resolve=>{accepted=resolve;});
  run('bridge=hold;state.busy=false;');
  elements.get('message').value='First';
  const sending=submit();
  context.window.fusionJavaScriptHandler.handle('state',JSON.stringify({account:{},connection:'ready',busy:false}));
  assert.equal(run('submitting'),true);
  elements.get('message').value='Draft typed while sending';
  accepted({ok:true});await sending;
  assert.equal(elements.get('message').value,'Draft typed while sending');
  // Image assets load once per ID, outside streamed state and Markdown updates.
  context.png=png;
  run('requests=[];bridge=async(action,payload)=>{requests.push({action,payload});return {images:{fixture:png}};};');
  context.renderMessageImages(element(),element(),[{id:'fixture',name:'Reference'}]);
  context.renderMessageImages(element(),element(),[{id:'fixture',name:'Reference'}]);
  await Promise.resolve();await Promise.resolve();
  assert.equal(run('requests.length'),1);
  console.log('Image UI checks passed: clipboard types, bounds, preparing/removing, image-only send, steering, failed drafts, submit races, and separate cached previews.');
})().catch(error=>{console.error(error);process.exitCode=1;});
