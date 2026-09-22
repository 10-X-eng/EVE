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
let dismissedUpdate = "";
let submitting = false;
let renderedThread = null;
let renderedProvider = null;
let renderedHistory = "";
let draftImages = [];
let draftImageRevision = 0;
let nextDraftImage = 0;
let clipboardRequest = null;
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
  if(!window.adsk?.fusionSendData) throw new Error("Open STEVE inside Fusion to connect.");
  const result = await window.adsk.fusionSendData(action,JSON.stringify(payload));
  if(result){const parsed=typeof result==="string"?JSON.parse(result):result;if(parsed.ok===false)throw new Error(parsed.error||"Fusion could not process that action.");return parsed;}
}
function act(action,payload={}) {
  return bridge(action,payload).catch((error)=>{state.error=error.message;dismissedError="";submitting=false;render();});
}

function openImage(url, name) {
  if (!SteveImages.imageURL(url)) return;
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
    try{const prepared=await SteveImages.prepare(item.file);Object.assign(item,prepared);delete item.file;}
    catch(error){draftImages=draftImages.filter(other=>other!==item);state.error=error.message;dismissedError="";}
    draftImageRevision++;renderDraftImages();render();
  }));
}
function pasteClipboardImage() {
  if (clipboardRequest || submitting || !state.account || state.connection !== "ready") return;
  if (draftImages.length >= 4) {state.error="Attach at most four images per message.";dismissedError="";render();return;}
  const request = {id:`paste-${Date.now()}-${++nextDraftImage}`, threadId:state.threadId};
  clipboardRequest=request;
  request.timer=setTimeout(()=>finishClipboardImage({requestId:request.id,error:"Image paste timed out. Copy the screenshot and paste again."}),15000);
  render();
  bridge("clipboardImage",{requestId:request.id}).catch(error=>finishClipboardImage({requestId:request.id,error:error.message}));
}
async function finishClipboardImage(result) {
  const request=clipboardRequest;
  if (!request || request.receiving || result.requestId!==request.id) return;
  request.receiving=true;
  clearTimeout(request.timer);
  try {
    if (state.threadId!==request.threadId || !state.account || state.connection!=="ready") return;
    if (result.error) throw new Error(result.error);
    if (!result.image) throw new Error("No image is available on the clipboard. Copy the screenshot itself, then paste.");
    await attachImages([SteveImages.clipboardFile(result.image)]);
  } catch(error) {state.error=error.message;dismissedError="";}
  finally {if(clipboardRequest===request)clipboardRequest=null;render();}
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
      if(!SteveImages.imageURL(url)){button.textContent="Image preview unavailable";return;}
      const img=document.createElement("img");img.src=url;img.alt=reference.name||"Reference image";img.loading="lazy";
      button.replaceChildren(img);button.disabled=false;button.title="View reference image";
      button.onclick=()=>openImage(url,reference.name||"Reference image");
    });
  });
}
async function reuseMessage(message) {
  if($("message").value.trim() || draftImages.length){state.error="Send or clear your current draft before reusing this message.";dismissedError="";render();return;}
  const provider=state.provider, threadId=state.threadId;
  try {
    const references=message.images||[];
    const result=references.length?await bridge("imageAssets",{ids:references.map(image=>image.id)}):{images:{}};
    if(state.provider!==provider || state.threadId!==threadId)return;
    if(references.some(image=>!SteveImages.imageURL(result?.images?.[image.id])))throw new Error("The saved image is unavailable. Paste it again.");
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

function createCodeActivity(article, message) {
  article.className = "message code-activity";
  article.innerHTML = '<details class="code-card"><summary><span class="code-symbol" aria-hidden="true">&lt;/&gt;</span><span class="code-copy"><span class="code-title"></span><span class="code-meta"></span></span><span class="code-chevron" aria-hidden="true">⌄</span></summary><pre tabindex="0" aria-label="Submitted Fusion Python"><code></code></pre></details>';
  const details = article.firstChild;
  details.open = !message.historical;
  return {details, code: article.querySelector("code"), pre: article.querySelector("pre"),
    title: article.querySelector(".code-title"), meta: article.querySelector(".code-meta")};
}

function updateCodeActivity(view, message) {
  const status = message.toolStatus || "unconfirmed";
  const phase = status === "running"
    ? (state.status === "Stopping" ? "Stopping" : state.waitingForFusion ? "Waiting for Fusion" : "Running in Fusion")
    : ({completed:"Completed", failed:"Failed", unconfirmed:"Completion unconfirmed"}[status] || "Completion unconfirmed");
  const lines = (message.code || "").split("\n").length;
  const meta = `${phase} · Python · ${lines} ${lines === 1 ? "line" : "lines"}`;
  const signature = JSON.stringify([message.code, message.title, meta]);
  if (view.signature === signature) return false;
  view.signature = signature;
  view.details.dataset.status = status;
  if (view.title.textContent !== message.title) view.title.textContent = message.title || "Fusion Python";
  if (view.meta.textContent !== meta) view.meta.textContent = meta;
  if (view.code.textContent !== message.code) {
    const follow = view.pre.scrollHeight - view.pre.scrollTop - view.pre.clientHeight < 36;
    view.code.textContent = message.code || "";
    if (follow) view.pre.scrollTop = view.pre.scrollHeight;
  }
  return true;
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
      let codeView;
      if (message.role === "tool") codeView = createCodeActivity(article, message);
      else article.innerHTML = `<div class="message-head">${message.role === "user" ? "YOU" : '<img src="mark.svg" alt=""> STEVE'}</div><div class="message-body"></div>`;
      if (view) conversation.replaceChild(article, view.article);
      else conversation.appendChild(article);
      view = {key, article, body: article.lastChild, text: null, codeView};
      if (!codeView) renderMessageImages(article,view.body,message.images||[]);
      messageViews[index] = view;
      changed = true;
    }
    if (view.codeView) { changed = updateCodeActivity(view.codeView, message) || changed; return; }
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
  const provider=state.provider||"chatgpt";
  if(renderedProvider && renderedProvider!==provider){
    if(clipboardRequest)clearTimeout(clipboardRequest.timer);
    draftImages=[];draftImageRevision++;imageCache.clear();clipboardRequest=null;
    $("message").value="";renderDraftImages();
  }
  renderedProvider=provider;
  if(threadChanged && renderedThread)imageCache.clear();
  renderedThread = state.threadId || null;
  const controls = JSON.stringify({...state, messages: undefined,
    hasMessages: state.messages.length > 0, draft: $("message").value, draftImageRevision, submitting, clipboardPending:!!clipboardRequest, dismissedError});
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
  renderGoal();
  const connected=state.connection==="ready";
  const local=state.provider==="ollama";
  const claude=state.provider==="claude";
  const signed=!!state.account && (!(local || claude) || state.models.length>0);
  const hasMessages=state.messages.length>0 && signed;
  $("app").classList.toggle("signed-out",!signed);
  $("welcome").hidden=hasMessages || !!state.runtimeIssue;
  $("runtime-setup").hidden=!state.runtimeIssue;
  $("conversation").hidden=!hasMessages;
  $("sign-in-card").hidden=signed;
  $("login").disabled=!connected || !state.accountChecked || state.loginPending;
  const grok=state.provider==="grok";
  const providerName=local?"Ollama":grok?"Grok / X":claude?"Claude":"ChatGPT";
  for(const id of ["provider","welcome-provider"]){$(id).value=state.provider||"chatgpt";$(id).disabled=!!state.busy || !!state.goalBusy || !!state.loginPending || state.connection==="starting";}
  $("login").textContent=claude?(!state.accountChecked?"Checking Claude Code…":"Check connection"):local?(!state.accountChecked?"Checking Ollama…":"Refresh models"):state.loginPending?"Signing in…":!state.accountChecked?"Checking your account…":grok?"Sign in with X / Grok ↗":"Sign in with ChatGPT ↗";
  $("sign-in-heading").textContent=local?"Your tools. Your local model.":"Your tools. Your AI.";
  $("sign-in-description").textContent=claude?(state.localStatus||"Sign in to Claude Code outside Fusion, then check the connection here."):local?(state.localStatus||"Start Ollama and choose a downloaded model. No sign-in needed."):"Connect your account and bring your thinking partner into Fusion.";
  $("sign-in-note").textContent=claude?"Experimental · Uses the account signed into Claude Code and its subscription limits. Web search is unavailable.":local?"Runs on this computer. Choose a model with tool support and at least 8K context. Web search is unavailable.":grok?"Uses your xAI account’s Grok access. Link your X account at grok.com if needed.":"Uses your subscription's Codex access";
  $("claude-controls").hidden=!claude;
  $("claude-version").textContent=state.providerVersion?`Claude Code ${state.providerVersion}`:"Claude Code · Version unavailable";
  $("claude-links").hidden=!claude;
  $("claude-refresh").disabled=state.busy || !connected;
  $("local-controls").hidden=!local;
  $("local-links").hidden=!local;
  $("local-status").textContent=state.localStatus||"Checking local Ollama…";
  $("local-refresh").disabled=state.busy || !connected;
  $("login-wait").hidden=!state.loginPending;
  $("grok-login-note").hidden=!grok || signed || !state.loginPending || !!state.device;
  $("device-login").hidden=local || claude || state.loginPending;
  $("device-login").disabled=!connected || !state.accountChecked;
  $("cancel-login").hidden=!state.loginPending;
  $("refresh-account").hidden=!state.loginPending;
  $("device-info").hidden=!state.device;
  $("device-code").textContent=state.device?.code||"";
  $("message").disabled=!signed || !connected;
  $("message").placeholder=signed?(state.busy?"Add a correction or steer STEVE…":"What are you working on?"):local?"Connect a local model to begin":"Sign in to start a conversation";
  const goalCommand = /^\/goal(?:\s|$)/.test($("message").value.trim());
  $("send").disabled=!signed || !connected || (!$("message").value.trim() && !draftImages.length) || draftImages.some(item=>!item.url) || !!clipboardRequest || submitting || (state.busy && !state.canSteer && !goalCommand) || !!state.goalBusy;
  const selectedModel=state.models.find(m=>m.id===state.model) || state.models.find(m=>m.isDefault);
  $("attach-images").disabled=!signed || !connected || draftImages.length>=4 || (local && selectedModel?.supportsImages===false);
  $("send").hidden=false;
  $("send").title=goalCommand?"Manage goal":state.busy?"Steer current response":"Send message";
  $("send").setAttribute("aria-label",$("send").title);
  $("stop").hidden=!state.busy && !state.goalBusy;
  $("stop").disabled=state.status==="Opening conversation";
  $("new-chat").disabled=state.busy || !!state.goalBusy || !hasMessages;
  $("model").disabled=!signed || state.busy || !!state.goalBusy;
  $("effort").disabled=!signed || state.busy || !!state.goalBusy || !(state.effortOptions||[]).length;
  $("logout").hidden=local || claude || !signed;
  $("logout").disabled=state.busy || !!state.goalBusy;
  $("debug-logging").checked=!!state.debugLogging;
  $("open-logs").title=state.debugLogPath || "Open local debug logs";
  const update=state.updateInfo;
  $("installed-version").textContent=state.version?`STEVE ${state.version}`:"STEVE";
  $("update-status").textContent=state.updateStatus||"Checks for new releases automatically.";
  $("check-updates").disabled=!!state.updateChecking;
  $("check-updates").textContent=state.updateChecking?"Checking…":"Check for updates";
  $("menu-update").hidden=!update;
  $("update-banner").hidden=!update || dismissedUpdate===update.version;
  $("update-title").textContent=update?`STEVE ${update.version} is available`:"";
  const download=state.updateDownload;
  const downloading=download?.state==="downloading";
  const downloaded=download?.state==="ready" && download.version===update?.version;
  const downloadLabel=downloading?`Downloading${download.percent==null?"…":` ${download.percent}%`}`:downloaded?"Open Downloads":"Download update";
  for(const id of ["download-update","menu-download"]){$(id).textContent=downloadLabel;$(id).disabled=downloading;}
  $("menu-download").hidden=!update;
  const downloadNote=download?.state==="error"?download.message:downloaded?"Saved and verified in Downloads. Close Fusion, extract the ZIP, and run the installer.":"Saves the ZIP to Downloads. Close Fusion before installing.";
  $("download-status").hidden=!download;
  $("download-status").textContent=downloadNote;
  $("update-hint").textContent=downloadNote;
  $("account-email").textContent=local?"Local Ollama":state.account?.email || (signed?`${providerName} account`:"Not signed in");
  $("account-plan").textContent=local?"localhost:11434 · No sign-in needed":signed?`${state.account.planType||providerName} · Connected`:`Use your ${providerName} account`;
  $("status").textContent=clipboardRequest?"Reading clipboard image…":state.waitingForFusion?state.waitingReason:state.status;
  const tools=state.busy && signed && state.connection==="ready" ? state.activeTools||[] : [];
  const tool=tools[0];
  const toolPhase=state.status==="Stopping"?"Stopping":state.waitingForFusion?"Waiting":"Using";
  $("tool-activity").hidden=!tool;
  const toolTitle=tool?tool.title:"";
  const toolName=tool?`${toolPhase} ${tool.name}${tools.length>1?` · +${tools.length-1} more`:""}`:"";
  // Keep the live region stable while response tokens arrive.
  if($("tool-title").textContent!==toolTitle) $("tool-title").textContent=toolTitle;
  if($("tool-name").textContent!==toolName) $("tool-name").textContent=toolName;
  $("tool-activity").title=tools.map(t=>`${t.name}: ${t.title}`).join("\n");
  $("task-target").hidden=!signed || !state.busy || !state.taskDocument;
  $("task-target").textContent=state.taskDocument?`Task: ${state.taskDocument.name||"No document"} · ${state.waitingForFusion?"Waiting":"Pinned"}`:"";
  $("task-target").title="This task keeps its original document and selection. It waits when another document or command is active.";
  $("preference-notice").hidden=!signed || !state.preferenceNotice;
  $("preference-notice").textContent=state.preferenceNotice||"";
  $("status-dot").className="status-dot"+(state.busy?" busy":signed&&connected?" ready":"");
  $("error").hidden=!state.error || state.error===dismissedError;
  $("error-text").textContent=state.error;
  $("reconnect-row").hidden=state.connection!=="disconnected";
  const modelsJSON=JSON.stringify([state.provider,state.models]);
  if(modelsJSON!==renderedModels){
    $("model").replaceChildren(new Option(local?"Local default":"Account default",""));
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
  if(action==="clipboardImage"){
    try{finishClipboardImage(JSON.parse(data));}catch(error){return "FAILED";}
  }
  if(action==="state"){
    try{state=JSON.parse(data);scheduleRender();}catch(error){return "FAILED";}
  }
  return "OK";
}};

function renderGoal() {
  const goal = state.goal;
  const labels = {active:"Working", paused:"Paused", blocked:"Blocked", budgetLimited:"Token limit reached", usageLimited:"Usage limit reached", complete:"Complete"};
  const label = goal ? labels[goal.status] || goal.status : "No goal yet";
  $("goal-strip").hidden = !goal;
  $("goal-strip-title").textContent = goal?.objective || "";
  $("goal-strip-status").textContent = label;
  $("goal-summary").textContent = goal ? `${label} · ${goal.objective}` : state.goalNotice || "Set an objective with a clear stopping point.";
  $("goal-usage").textContent = goal ? `${Number(goal.tokensUsed || 0).toLocaleString()}${goal.tokenBudget == null ? "" : ` / ${Number(goal.tokenBudget).toLocaleString()}`} tokens · ${Math.floor((goal.timeUsedSeconds || 0) / 60)} min` : "";
  $("goal-target-note").textContent = goal && state.goalHasTarget ? "Resuming keeps this goal’s original document and selection." : "Starting or resuming uses the active Fusion document. Open the intended document first.";
  const unavailable = !state.account || state.connection !== "ready" || !!state.goalBusy;
  $("goal-button").disabled = unavailable;
  $("goal-pause").hidden = !goal || (goal.status !== "active" && !state.busy);
  $("goal-pause").disabled = unavailable;
  $("goal-resume").hidden = !goal || goal.status === "active" || goal.status === "complete";
  $("goal-resume").disabled = unavailable || !!state.busy;
  $("goal-resume").textContent = goal?.status === "budgetLimited" ? "Resume with budget below" : "Resume";
  $("goal-clear").hidden = !goal;
  $("goal-clear").disabled = unavailable;
  $("goal-save").disabled = unavailable || !!state.busy;
  $("goal-save").textContent = goal ? "Save and start" : "Start goal";
}

function openGoal(edit = false) {
  $("goal-objective").value = state.goal?.objective || "";
  $("goal-budget").value = state.goal?.tokenBudget ?? "";
  renderGoal();
  if (!$("goal-dialog").open) $("goal-dialog").showModal();
  if (edit || !state.goal) $("goal-objective").focus();
  act("goal", {command:"status"});
}

function goalBudget() {
  const value = $("goal-budget").value.trim();
  const budget = value ? Number(value) : null;
  if (budget !== null && (!Number.isSafeInteger(budget) || budget <= 0)) throw new Error("Enter a positive whole token budget, or leave it blank.");
  return budget;
}

$("login").onclick=()=>state.provider==="ollama"?act("accountRefresh",{refreshModels:true}):act("login");
$("claude-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("install-claude").onclick=()=>act("setupHelp",{page:"claude"});
$("goal-button").onclick=()=>openGoal();
$("goal-strip").onclick=()=>openGoal();
$("goal-close").onclick=()=>$("goal-dialog").close();
$("goal-pause").onclick=()=>act("goal",{command:"pause"});
$("goal-clear").onclick=()=>act("goal",{command:"clear"});
$("goal-resume").onclick=()=>{
  try { act("goal",{command:"resume",tokenBudget:goalBudget()}); $("goal-dialog").close(); }
  catch(error) { state.error=error.message; $("goal-dialog").close(); render(); }
};
$("goal-form").onsubmit=(event)=>{
  event.preventDefault();
  try { act("goal",{command:"set",objective:$("goal-objective").value.trim(),tokenBudget:goalBudget()}); $("goal-dialog").close(); }
  catch(error) { state.error=error.message; $("goal-dialog").close(); render(); }
};
$("local-refresh").onclick=()=>act("accountRefresh",{refreshModels:true});
$("install-ollama").onclick=()=>act("setupHelp",{page:"ollama"});
$("local-help").onclick=$("local-setup").onclick=()=>act("setupHelp",{page:"local"});
$("device-login").onclick=()=>act("deviceLogin");
$("cancel-login").onclick=()=>act("cancelLogin");
$("refresh-account").onclick=()=>act("accountRefresh",{refreshToken:true});
$("logout").onclick=()=>{act("logout");$("account-menu").hidden=true;$("account-button").setAttribute("aria-expanded","false");};
$("reconnect").onclick=()=>act("connect");
$("repair-steve").onclick=()=>act("setupHelp",{page:"steve"});
$("install-codex").onclick=()=>act("setupHelp",{page:"codex"});
$("debug-logging").onchange=(event)=>act("debugLogging",{enabled:event.target.checked});
$("open-logs").onclick=()=>act("openLogs");
$("check-updates").onclick=()=>{dismissedUpdate="";act("checkUpdates");};
$("menu-update").onclick=()=>act("openUpdate",{page:"notes"});
$("download-update").onclick=()=>act(state.updateDownload?.state==="ready" && state.updateDownload.version===state.updateInfo?.version?"openDownloads":"downloadUpdate");
$("menu-download").onclick=$("download-update").onclick;
$("update-notes").onclick=()=>act("openUpdate",{page:"notes"});
$("dismiss-update").onclick=()=>{dismissedUpdate=state.updateInfo?.version||"";renderedControls="";render();};
$("new-chat").onclick=()=>{showHistory(false);act("new");};
$("history-button").onclick=()=>{const open=$("history-panel").hidden;showHistory(open);if(open){renderHistory();act("history");}};
$("history-close").onclick=()=>{showHistory(false);$("history-button").focus();};
$("history-search").oninput=renderHistory;
$("history-more").onclick=()=>act("history",{more:true});
$("stop").onclick=()=>act("stop");
$("dismiss-error").onclick=()=>{dismissedError=state.error;render();};
$("model").onchange=(event)=>act("model",{model:event.target.value});
$("provider").onchange=(event)=>act("provider",{provider:event.target.value});
$("welcome-provider").onchange=$("provider").onchange;
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
  if(event.isTrusted===false)return;
  const clipboard=event.clipboardData;
  const items=Array.from(clipboard?.items||[]);
  const hasImage=items.some(item=>item.kind==="file" && item.type.startsWith("image/"));
  const hasText=items.some(item=>item.kind==="string" && item.type==="text/plain") || Array.from(clipboard?.types||[]).includes("text/plain");
  if(hasText && !hasImage)return; // Text remains the browser's native paste operation.
  event.preventDefault();pasteClipboardImage();
};
$("attach-images").onclick=()=>$("image-files").click();
if(typeof navigator!=="undefined" && /Mac/.test(navigator.platform||""))$("attach-images").title="Attach images · ⌘V to paste";
$("image-files").onchange=(event)=>{const files=Array.from(event.target.files||[]);event.target.value="";attachImages(files);};
$("close-image").onclick=()=>$("image-viewer").close();
$("image-viewer").onclick=(event)=>{if(event.target===$("image-viewer"))$("image-viewer").close();};
$("image-viewer").onclose=()=>$("expanded-image").removeAttribute("src");
$("composer").onsubmit=async(event)=>{
  event.preventDefault();const text=$("message").value.trim();
  const goalCommand=/^\/goal(?:\s|$)/.test(text);
  if((!text&&!draftImages.length)||draftImages.some(item=>!item.url)||clipboardRequest||(state.busy&&!state.canSteer&&!goalCommand)||submitting||state.goalBusy||!state.account||state.connection!=="ready")return;
  if(/^\/goal(?:\s+(?:edit|status|help))?$/.test(text) && !draftImages.length){$("message").value="";resize();openGoal(text.endsWith("edit"));return;}
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
  state.error="Open STEVE from the Fusion toolbar. This panel connects through the Fusion add-in.";render();
}
initialize();
