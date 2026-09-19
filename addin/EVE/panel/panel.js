/* Plain browser UI. Fusion is the only production bridge; previews are explicitly marked. */
"use strict";
const $ = (id) => document.getElementById(id);
const preview = new URLSearchParams(location.search).get("preview");
let state = {connection:"starting",account:null,accountChecked:false,models:[],model:"",messages:[],busy:false,loginPending:false,status:"Checking your account",error:""};
let messageViews = [];
let renderedControls = "";
let renderFrame = null;
let renderedModels = "";
let renderedEfforts = "";
let dismissedError = "";
let submitting = false;
let renderedThread = null;
let renderedHistory = "";
let draftImages = [];
let draftImageRevision = 0;
let nextDraftImage = 0;
const imageCache = new Map();

function escapeHTML(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
}
function inline(text) {
  // Code spans are isolated so markdown cannot rewrite their contents.
  return text.split(/(`[^`]+`)/g).map((part) => {
    if (part.startsWith("`") && part.endsWith("`")) return `<code>${escapeHTML(part.slice(1,-1))}</code>`;
    return escapeHTML(part).replace(/\*\*([^*]+)\*\*/g,"<strong>$1</strong>").replace(/\*([^*]+)\*/g,"<em>$1</em>");
  }).join("");
}
function markdown(text) {
  // Parse fences line by line, including unfinished blocks during streaming.
  let html = "", paragraph = [], list = null, code = null;
  const flush = () => { if(paragraph.length){html += `<p>${paragraph.map(inline).join("<br>")}</p>`;paragraph=[];} if(list){html+=`</${list}>`;list=null;} };
  for (const line of String(text).split("\n")) {
    if (/^\s*```/.test(line)) {
      if(code !== null){html += `<pre><code>${escapeHTML(code.join("\n"))}</code></pre>`;code=null;}
      else{flush();code=[];}
      continue;
    }
    if(code !== null){code.push(line);continue;}
    if(!line.trim()){flush();continue;}
    const heading=line.match(/^#{1,4}\s+(.+)$/);
    const bullet=line.match(/^\s*([-*]|\d+\.)\s+(.+)$/);
    if(heading){flush();html+=`<h3>${inline(heading[1])}</h3>`;}
    else if(bullet){const tag=/\d/.test(bullet[1])?"ol":"ul";if(list!==tag){flush();html+=`<${tag}>`;list=tag;}html+=`<li>${inline(bullet[2])}</li>`;}
    else if(line.startsWith("> ")){flush();html+=`<blockquote>${inline(line.slice(2))}</blockquote>`;}
    else{if(list)flush();paragraph.push(line);}
  }
  if(code !== null)html+=`<pre><code>${escapeHTML(code.join("\n"))}</code></pre>`;
  flush();return html;
}

async function bridge(action,payload={}) {
  if(preview){previewAction(action,payload);return {ok:true};}
  if(!window.adsk?.fusionSendData) throw new Error("Open EVE inside Fusion to connect.");
  const result = await window.adsk.fusionSendData(action,JSON.stringify(payload));
  if(result){const parsed=typeof result==="string"?JSON.parse(result):result;if(parsed.ok===false)throw new Error(parsed.error||"Fusion could not process that action.");return parsed;}
}
function act(action,payload={}) {
  return bridge(action,payload).catch((error)=>{state.error=error.message;dismissedError="";submitting=false;render();});
}

function openImage(url, name) {
  if (!EveImages.imageURL(url)) return;
  $("expanded-image").src = url;
  $("expanded-image").alt = name;
  $("image-viewer").showModal();
}
function renderDraftImages() {
  $("image-drafts").hidden = !draftImages.length;
  $("image-drafts").replaceChildren(...draftImages.map(item => {
    const chip = document.createElement("div");chip.className="image-chip";
    const thumbnail = document.createElement("button");thumbnail.type="button";thumbnail.className="image-thumbnail";
    thumbnail.title=item.name;thumbnail.disabled=!item.url;
    if(item.url){const img=document.createElement("img");img.src=item.url;img.alt=item.name;thumbnail.append(img);thumbnail.onclick=()=>openImage(item.url,item.name);}
    else thumbnail.textContent="Preparing…";
    const remove=document.createElement("button");remove.type="button";remove.className="remove-image";remove.textContent="×";
    remove.setAttribute("aria-label",`Remove ${item.name}`);
    remove.onclick=()=>{draftImages=draftImages.filter(other=>other!==item);draftImageRevision++;renderDraftImages();render();};
    chip.append(thumbnail,remove);return chip;
  }));
  $("image-hint").hidden=!draftImages.length;
  $("image-hint").textContent=draftImages.some(item=>!item.url)?"Preparing images…":
    `${draftImages.length}/4 images attached${draftImages.some(item=>item.compressed)?" · Resized for chat":""}`;
}
async function attachImages(files) {
  if(!state.account || state.connection!=="ready")return;
  const available=4-draftImages.length;
  if(files.length>available){state.error="Attach at most four images per message.";dismissedError="";render();return;}
  const items=files.map(file=>({id:++nextDraftImage,name:file.name||"Pasted image",file}));
  draftImages.push(...items);draftImageRevision++;renderDraftImages();render();
  await Promise.all(items.map(async item=>{
    try{const prepared=await EveImages.prepare(item.file);Object.assign(item,prepared);delete item.file;}
    catch(error){draftImages=draftImages.filter(other=>other!==item);state.error=error.message;dismissedError="";}
    draftImageRevision++;renderDraftImages();render();
  }));
}
function renderMessageImages(article, body, images) {
  if(!images.length)return;
  const gallery=document.createElement("div");gallery.className="message-images";
  article.insertBefore(gallery,body);
  images.forEach(reference=>{
    const button=document.createElement("button");button.type="button";button.className="saved-image";
    button.textContent=reference.name||"Reference image";button.disabled=true;
    gallery.append(button);
    if(!reference.id)return;
    if(!imageCache.has(reference.id)) imageCache.set(reference.id,
      bridge("imageAssets",{ids:[reference.id]}).then(result=>result?.images?.[reference.id]).catch(()=>null));
    imageCache.get(reference.id).then(url=>{
      if(!EveImages.imageURL(url)){button.textContent="Image preview unavailable";return;}
      const img=document.createElement("img");img.src=url;img.alt=reference.name||"Reference image";img.loading="lazy";
      button.replaceChildren(img);button.disabled=false;button.title="View reference image";
      button.onclick=()=>openImage(url,reference.name||"Reference image");
    });
  });
}
async function reuseMessage(message) {
  if($("message").value.trim() || draftImages.length){state.error="Send or clear your current draft before reusing this message.";dismissedError="";render();return;}
  try {
    const references=message.images||[];
    const result=references.length?await bridge("imageAssets",{ids:references.map(image=>image.id)}):{images:{}};
    if(references.some(image=>!EveImages.imageURL(result?.images?.[image.id])))throw new Error("The saved image is unavailable. Paste it again.");
    // A user may begin another draft while the native bridge is returning.
    if($("message").value.trim() || draftImages.length)return;
    draftImages=references.map(image=>({id:++nextDraftImage,name:image.name,url:result.images[image.id]}));
    $("message").value=message.text;draftImageRevision++;renderDraftImages();resize();$("message").focus();
  } catch(error){state.error=error.message;dismissedError="";}
  render();
}
// Reconcile the safe Markdown tree without detaching existing paragraphs, code
// blocks or text. Appending a token should not restart animations or selection.
function patchChildren(parent, next) {
  const desired = Array.from(next.childNodes);
  desired.forEach((node, index) => {
    const current = parent.childNodes[index];
    if (!current) { parent.appendChild(node); return; }
    if (current.nodeType !== node.nodeType || current.nodeName !== node.nodeName) {
      parent.replaceChild(node, current); return;
    }
    if (node.nodeType === 3) {
      if (current.data !== node.data) {
        if (node.data.startsWith(current.data)) current.appendData(node.data.slice(current.data.length));
        else current.replaceData(0, current.length, node.data);
      }
    } else {
      patchChildren(current, node);
    }
  });
  while (parent.childNodes.length > desired.length) parent.lastChild.remove();
}

function renderMessages() {
  const conversation = $("conversation");
  let changed = false;
  state.messages.forEach((message, index) => {
    const key = `${state.threadId || ""}:${message.role}:${message.id ?? index}`;
    let view = messageViews[index];
    if (!view || view.key !== key) {
      const article = document.createElement("article");
      article.className = `message ${message.role === "user" ? "user" : "assistant"}`;
      article.innerHTML = `<div class="message-head">${message.role === "user" ? "YOU" : '<img src="mark.svg" alt=""> EVE'}</div><div class="message-body"></div>`;
      if (view) conversation.replaceChild(article, view.article);
      else conversation.appendChild(article);
      view = {key, article, body: article.lastChild, text: null};
      renderMessageImages(article,view.body,message.images||[]);
      messageViews[index] = view;
      changed = true;
    }
    const signature=JSON.stringify([message.text,message.delivery,message.selectionCount]);
    if (view.text !== signature) {
      const template = document.createElement("template");
      template.innerHTML = message.role === "user"
        ? `${message.text?`<p>${escapeHTML(message.text).replace(/\n/g,"<br>")}</p>`:""}${message.selectionCount?`<small class="message-note">${Number(message.selectionCount)} selected at send</small>`:""}${message.delivery==="pending"?'<small class="message-note">Sending…</small>':message.delivery==="failed"?'<small class="message-note delivery-failed">Delivery unconfirmed</small><button class="text-button reuse-message" type="button">Reuse message</button>':""}` : markdown(message.text);
      patchChildren(view.body, template.content);
      const reuse=view.body.querySelector(".reuse-message");if(reuse)reuse.onclick=()=>reuseMessage(message);
      view.text = signature;
      changed = true;
    }
  });
  while (messageViews.length > state.messages.length) {
    messageViews.pop().article.remove();
    changed = true;
  }
  return changed;
}

function scheduleRender() {
  if (renderFrame !== null) return;
  renderFrame = requestAnimationFrame(() => { renderFrame = null; render(); });
}

function render() {
  const scroll = $("scroll-area");
  // Read before changing content, and finish scrolling in this same frame.
  const nearBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 100;
  const wasEmpty = messageViews.length === 0;
  const threadChanged = renderedThread !== (state.threadId || null);
  if(threadChanged && renderedThread)imageCache.clear();
  renderedThread = state.threadId || null;
  const controls = JSON.stringify({...state, messages: undefined,
    hasMessages: state.messages.length > 0, draft: $("message").value, draftImageRevision, submitting, dismissedError});
  if (controls !== renderedControls) {
    renderControls();
    renderedControls = controls;
  }
  if (renderMessages()) {
    if (!state.messages.length) scroll.scrollTop = 0;
    else if (nearBottom || wasEmpty || threadChanged) scroll.scrollTop = scroll.scrollHeight;
  }
}

function renderControls() {
  const connected=state.connection==="ready";
  const signed=!!state.account;
  const hasMessages=state.messages.length>0 && signed;
  $("app").classList.toggle("signed-out",!signed);
  $("welcome").hidden=hasMessages || !!state.runtimeIssue;
  $("runtime-setup").hidden=!state.runtimeIssue;
  $("conversation").hidden=!hasMessages;
  $("sign-in-card").hidden=signed;
  $("login").disabled=!connected || !state.accountChecked || state.loginPending;
  $("login").textContent=state.loginPending?"Signing in…":!state.accountChecked?"Checking your account…":"Sign in with ChatGPT ↗";
  $("login-wait").hidden=!state.loginPending;
  $("device-login").hidden=state.loginPending;
  $("device-login").disabled=!connected || !state.accountChecked;
  $("cancel-login").hidden=!state.loginPending;
  $("refresh-account").hidden=!state.loginPending;
  $("device-info").hidden=!state.device;
  $("device-code").textContent=state.device?.code||"";
  $("message").disabled=!signed || !connected;
  $("message").placeholder=signed?(state.busy?"Add a correction or steer EVE…":"What are you working on?"):"Sign in to start a conversation";
  $("send").disabled=!signed || !connected || (!$("message").value.trim() && !draftImages.length) || draftImages.some(item=>!item.url) || submitting || (state.busy && !state.canSteer);
  $("attach-images").disabled=!signed || !connected || draftImages.length>=4;
  $("send").hidden=false;
  $("send").title=state.busy?"Steer current response":"Send message";
  $("send").setAttribute("aria-label",$("send").title);
  $("stop").hidden=!state.busy;
  $("stop").disabled=state.status==="Opening conversation";
  $("new-chat").disabled=state.busy || !hasMessages;
  $("model").disabled=!signed || state.busy;
  $("effort").disabled=!signed || state.busy || !(state.effortOptions||[]).length;
  $("logout").hidden=!signed;
  $("logout").disabled=state.busy;
  $("debug-logging").checked=!!state.debugLogging;
  $("open-logs").title=state.debugLogPath || "Open local debug logs";
  $("account-email").textContent=state.account?.email || (signed?"ChatGPT account":"Not signed in");
  $("account-plan").textContent=signed?`${state.account.planType||"ChatGPT"} · Connected through Codex`:"Use your ChatGPT account";
  $("status").textContent=state.waitingForFusion?state.waitingReason:state.status;
  $("task-target").hidden=!signed || !state.busy || !state.taskDocument;
  $("task-target").textContent=state.taskDocument?`Task: ${state.taskDocument.name||"No document"} · ${state.waitingForFusion?"Waiting":"Pinned"}`:"";
  $("task-target").title="This task keeps its original document and selection. It waits when another document or command is active.";
  $("preference-notice").hidden=!signed || !state.preferenceNotice;
  $("preference-notice").textContent=state.preferenceNotice||"";
  $("status-dot").className="status-dot"+(state.busy?" busy":signed&&connected?" ready":"");
  $("error").hidden=!state.error || state.error===dismissedError;
  $("error-text").textContent=state.error;
  $("reconnect-row").hidden=state.connection!=="disconnected";
  const modelsJSON=JSON.stringify(state.models);
  if(modelsJSON!==renderedModels){
    $("model").replaceChildren(new Option("Account default",""));
    state.models.forEach((model)=>$("model").add(new Option(model.name,model.id)));
    renderedModels=modelsJSON;
  }
  $("model").value=state.model;
  const efforts=state.effortOptions||[];
  const effortsJSON=JSON.stringify([efforts,state.defaultEffort]);
  if(effortsJSON!==renderedEfforts){
    const labels={none:"None",minimal:"Minimal",low:"Low",medium:"Medium",high:"High",xhigh:"Extra high",max:"Max",ultra:"Ultra"};
    $("effort").replaceChildren(new Option(state.defaultEffort?`Default (${labels[state.defaultEffort]||state.defaultEffort})`:"Default",""));
    efforts.forEach((effort)=>{const option=new Option(labels[effort.id]||effort.id,effort.id);option.title=effort.description;$("effort").add(option);});
    renderedEfforts=effortsJSON;
  }
  $("effort").value=state.effort||"";
  $("thinking").hidden=!state.busy || state.status==="Writing" || state.waitingForFusion;
  $("history-button").disabled=!signed || !connected || state.busy;
  if(!signed)showHistory(false);
  renderHistory();
}

function showHistory(open) {
  $("history-panel").hidden=!open;
  $("history-button").setAttribute("aria-expanded",String(open));
  if(open){$("account-menu").hidden=true;$("account-button").setAttribute("aria-expanded","false");$("history-search").focus();}
}
function renderHistory() {
  const query=$("history-search").value.trim().toLocaleLowerCase();
  const history=state.history||[];
  const signature=JSON.stringify([history,query,state.threadId,state.historyLoading,state.busy,state.historyCursor]);
  if(signature===renderedHistory)return;
  renderedHistory=signature;
  const entries=history.filter(entry=>entry.title.toLocaleLowerCase().includes(query));
  $("history-list").replaceChildren(...entries.map(entry=>{
    const button=document.createElement("button");button.className="history-entry";
    button.disabled=state.busy||state.historyLoading;
    button.setAttribute("aria-current",String(entry.id===state.threadId));
    const title=document.createElement("strong");title.textContent=entry.title;
    const date=document.createElement("small");date.textContent=entry.updatedAt?new Date(entry.updatedAt*1000).toLocaleDateString(undefined,{month:"short",day:"numeric",year:"numeric"}):"Saved conversation";
    button.append(title,date);
    button.onclick=()=>{showHistory(false);act("openHistory",{threadId:entry.id});};
    return button;
  }));
  $("history-empty").hidden=entries.length>0;
  $("history-empty").textContent=state.historyLoading?"Loading conversations…":query?"No matching conversations in the loaded history.":"Your conversations will appear here after your first message.";
  $("history-more").hidden=!state.historyCursor;
  $("history-more").disabled=state.historyLoading||state.busy;
}

window.fusionJavaScriptHandler={handle(action,data){
  if(action==="state"){
    try{state=JSON.parse(data);scheduleRender();}catch(error){return "FAILED";}
  }
  return "OK";
}};

$("login").onclick=()=>act("login");
$("device-login").onclick=()=>act("deviceLogin");
$("cancel-login").onclick=()=>act("cancelLogin");
$("refresh-account").onclick=()=>act("accountRefresh",{refreshToken:true});
$("logout").onclick=()=>{act("logout");$("account-menu").hidden=true;$("account-button").setAttribute("aria-expanded","false");};
$("reconnect").onclick=()=>act("connect");
$("repair-eve").onclick=()=>act("setupHelp",{page:"eve"});
$("install-codex").onclick=()=>act("setupHelp",{page:"codex"});
$("debug-logging").onchange=(event)=>act("debugLogging",{enabled:event.target.checked});
$("open-logs").onclick=()=>act("openLogs");
$("new-chat").onclick=()=>{showHistory(false);act("new");};
$("history-button").onclick=()=>{const open=$("history-panel").hidden;showHistory(open);if(open){renderHistory();act("history");}};
$("history-close").onclick=()=>{showHistory(false);$("history-button").focus();};
$("history-search").oninput=renderHistory;
$("history-more").onclick=()=>act("history",{more:true});
$("stop").onclick=()=>act("stop");
$("dismiss-error").onclick=()=>{dismissedError=state.error;render();};
$("model").onchange=(event)=>act("model",{model:event.target.value});
$("effort").onchange=(event)=>act("effort",{effort:event.target.value});
$("account-button").onclick=()=>{const menu=$("account-menu");menu.hidden=!menu.hidden;$("account-button").setAttribute("aria-expanded",String(!menu.hidden));};
// Returning from the external browser should immediately reveal a saved sign-in.
let lastAccountCheck=0;
function checkAccountOnReturn(){
  if(!preview && state.connection==="ready" && !state.busy && Date.now()-lastAccountCheck>1500){
    lastAccountCheck=Date.now();act("accountRefresh");
  }
}
window.addEventListener("focus",checkAccountOnReturn);
document.addEventListener("visibilitychange",()=>{if(!document.hidden)checkAccountOnReturn();});
document.addEventListener("keydown",(event)=>{if(event.key==="Escape"){showHistory(false);$("account-menu").hidden=true;$("account-button").setAttribute("aria-expanded","false");}});
document.addEventListener("click",(event)=>{if(!event.target.closest("#account-menu, #account-button")){$("account-menu").hidden=true;$("account-button").setAttribute("aria-expanded","false");}});
document.querySelectorAll(".suggestion").forEach((button)=>button.onclick=()=>{
  if(!state.account){$("login").focus();return;}
  $("message").value=button.dataset.prompt;resize();$("message").focus();render();
});
function resize(){const input=$("message");input.style.height="auto";input.style.height=Math.min(input.scrollHeight,170)+"px";}
$("message").oninput=()=>{resize();render();};
$("message").onkeydown=(event)=>{if(event.key==="Enter"&&!event.shiftKey&&!event.isComposing){event.preventDefault();$("composer").requestSubmit();}};
$("message").onpaste=(event)=>{
  const files=EveImages.pasteFiles(event.clipboardData);
  if(!files.length)return; // Keep ordinary text paste native.
  event.preventDefault();attachImages(files);
};
$("attach-images").onclick=()=>$("image-files").click();
$("image-files").onchange=(event)=>{const files=Array.from(event.target.files||[]);event.target.value="";attachImages(files);};
$("close-image").onclick=()=>$("image-viewer").close();
$("image-viewer").onclick=(event)=>{if(event.target===$("image-viewer"))$("image-viewer").close();};
$("image-viewer").onclose=()=>$("expanded-image").removeAttribute("src");
$("composer").onsubmit=async(event)=>{
  event.preventDefault();const text=$("message").value.trim();
  if((!text&&!draftImages.length)||draftImages.some(item=>!item.url)||(state.busy&&!state.canSteer)||submitting||!state.account||state.connection!=="ready")return;
  const sentImages=draftImages.slice();const draftText=$("message").value;
  dismissedError="";submitting=true;render();
  try{
    await bridge(state.busy?"steer":"send",{text,images:sentImages.map(({name,url})=>({name,url})),threadId:state.threadId,turnId:state.turnId});
    if($("message").value===draftText)$("message").value="";
    draftImages=draftImages.filter(item=>!sentImages.includes(item));draftImageRevision++;renderDraftImages();resize();
  }
  catch(error){state.error=error.message;}
  submitting=false;render();
};

// Explicit design preview. No account connection or AI calls are made in this mode.
let previewTimer;
function previewAction(action,payload){
  if(action==="login"||action==="deviceLogin"){
    state.account={email:"designer@example.com",planType:"Plus"};state.status="Ready";
    state.models=[{id:"preview-model",name:"Preview model"}];
  }else if(action==="logout"){state.account=null;state.messages=[];state.status="Sign in to begin";}
  else if(action==="new"){state.messages=[];state.status="Ready";}
  else if(action==="model"){state.model=payload.model;}
  else if(action==="effort"){state.effort=payload.effort;}
  else if(action==="debugLogging"){state.debugLogging=payload.enabled;}
  else if(action==="send"){
    state.messages.push({role:"user",text:payload.text});state.busy=true;state.status="Thinking";
    previewTimer=setTimeout(()=>{state.messages.push({role:"assistant",text:"Start with the **design intent**: what should stay fixed, and what should be easy to change?\n\nFor a mounting bracket, I'd define three parameters first:\n\n1. **Plate thickness** — driven by material and load.\n2. **Hole spacing** — matched to the parts it connects.\n3. **Bend height** — enough clearance for assembly.\n\nThen build a fully constrained sketch around the origin.\n\nWhat will your bracket attach to?"});state.busy=false;state.status="Ready";render();},900);
  }else if(action==="stop"){clearTimeout(previewTimer);state.busy=false;state.status="Stopped";}
  render();
}
async function initialize(){
  render();
  if(preview){
    $("preview-banner").hidden=false;state.connection="ready";state.accountChecked=true;state.status="Sign in to begin";
    if(preview==="chat"){previewAction("login",{});previewAction("send",{text:"I'm designing a mounting bracket. Where should I start?"});}
    render();return;
  }
  for(let attempt=0;attempt<50;attempt++){
    if(window.adsk?.fusionSendData){await act("sync");return;}
    await new Promise((resolve)=>setTimeout(resolve,100));
  }
  state.connection="disconnected";state.status="Fusion connection unavailable";
  state.error="Open EVE from the Fusion toolbar. This panel connects through the Fusion add-in.";render();
}
initialize();
