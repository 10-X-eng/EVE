/* Shared library UI. Pixel requests are separate from streamed conversation state. */
"use strict";
const SteveGallery = (() => {
  let options, sequence=0, revision=0, nextOffset=null, query='', queue=Promise.resolve();
  const pending=new Map();
  const el=id=>document.getElementById(id);
  function receive(result) {
    const request=pending.get(result.requestId);
    if(!request)return;
    pending.delete(result.requestId);clearTimeout(request.timer);
    if(result.ok===false)request.reject(new Error(result.error||'The gallery request failed.'));
    else request.resolve(result);
  }
  function rpc(action,payload={}) {
    const task=queue.then(()=>new Promise((resolve,reject)=>{
      const requestId='gallery-'+Date.now()+'-'+(++sequence);
      const timer=setTimeout(()=>receive({requestId,ok:false,error:'The gallery took too long. Try refreshing it.'}),120000);
      pending.set(requestId,{resolve,reject,timer});
      options.bridge('gallery',{action,...payload,requestId}).then(result=>{
        if(!result?.pending)receive({requestId,...result});
      }).catch(error=>receive({requestId,ok:false,error:error.message}));
    }));
    queue=task.catch(()=>{});return task;
  }
  function notice(message) {el('gallery-status').textContent=message;}
  function close(focus=false) {
    revision++;el('gallery-panel').hidden=true;
    el('gallery-button').setAttribute('aria-expanded','false');
    if(focus)el('gallery-button').focus();
  }
  async function refresh(offset=0) {
    const current=++revision;
    el('gallery-more').disabled=true;notice('Loading images…');
    try {
      const result=await rpc('list',{query,offset});
      if(current!==revision)return;
      if(!offset)el('gallery-grid').replaceChildren();
      nextOffset=result.nextOffset;
      el('gallery-more').hidden=nextOffset==null;
      el('gallery-more').disabled=false;
      const warnings=result.migration;
      notice(`${result.total} ${result.total===1?'image':'images'}`+
        (warnings?.unavailable?' · Some damaged images could not be imported. Their files were kept.':'')+
        (warnings?.unreadableChatIndexes?' · Some original names could not be recovered.':''));
      el('gallery-empty').hidden=result.total!==0;
      el('gallery-empty').textContent=query?'No images match your search.':'Import a reference or send an image in chat to start your gallery.';
      const cards=result.images.map(item=>makeCard(item,current));
      for(const {card} of cards)el('gallery-grid').append(card);
      // Read previews one at a time; switching pages stops adding old previews.
      for(const {item,preview} of cards) {
        if(current!==revision)return;
        try {
          const result=await rpc('asset',{imageId:item.imageId});
          if(current!==revision)return;
          const prepared=await SteveImages.prepare(SteveImages.storedFile(result.image.url,item.name));
          if(current!==revision)return;
          const img=document.createElement('img');img.src=prepared.url;img.alt=item.name;
          preview.replaceChildren(img);preview.disabled=false;
        } catch(error) {if(current===revision){preview.textContent='Preview unavailable';preview.title=error.message;}}
      }
    } catch(error) {if(current===revision)notice(error.message);}
  }
  function button(label,action) {
    const node=document.createElement('button');node.type='button';node.className='chip-button';node.textContent=label;
    node.onclick=async()=>{node.disabled=true;try{await action();}catch(error){notice(error.message);}finally{node.disabled=false;}};
    return node;
  }
  function makeCard(item,current) {
    const card=document.createElement('article');card.className='gallery-card';card.dataset.imageId=item.imageId;
    const preview=button('Loading preview…',async()=>{
      const result=await rpc('asset',{imageId:item.imageId});
      if(card.isConnected && !el('gallery-panel').hidden)options.openImage(result.image.url,item.name);
    });preview.className='gallery-preview';preview.disabled=true;
    const name=document.createElement('input');name.value=item.name;name.maxLength=120;
    name.setAttribute('aria-label','Image name');name.title='Edit name, then press Enter or leave the field to save';
    name.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();name.blur();}};
    name.onchange=async()=>{
      name.disabled=true;
      try{await rpc('change',{imageId:item.imageId,name:name.value});item.name=name.value.trim();notice('Name saved.');}
      catch(error){name.value=item.name;notice(error.message);}finally{name.disabled=false;}
    };
    const label=document.createElement('label');label.className='gallery-access';
    const toggle=document.createElement('input');toggle.type='checkbox';toggle.checked=item.enabled;
    const text=document.createElement('span');text.textContent='Available to STEVE';label.append(toggle,text);
    toggle.onchange=async()=>{
      toggle.disabled=true;
      try{await rpc('change',{imageId:item.imageId,enabled:toggle.checked});item.enabled=toggle.checked;notice(toggle.checked?'Available in every conversation.':'Hidden from future gallery lookups.');}
      catch(error){toggle.checked=item.enabled;notice(error.message);}finally{toggle.disabled=false;}
    };
    const actions=document.createElement('div');actions.className='gallery-actions';
    actions.append(button('Attach',async()=>{
      const context=options.context();
      if(!options.canAttach())throw new Error('Connect a model that supports images and leave room in your draft.');
      const result=await rpc('asset',{imageId:item.imageId});
      if(context!==options.context() || !options.canAttach())throw new Error('The conversation changed. Choose the image again.');
      await options.attach(SteveImages.storedFile(result.image.url,item.name));
      close();el('message').focus();
    }),button('Remove',async()=>{
      await rpc('remove',{imageId:item.imageId});await refresh();
    }));
    card.append(preview,name,label,actions);return {card,preview,item};
  }
  async function importFiles(files) {
    if(files.length>20){notice('Import up to 20 images at a time.');return;}
    const control=el('gallery-import');control.disabled=true;
    try {
      for(const file of files) {
        if(!['image/png','image/jpeg','image/webp'].includes(file.type) || file.size>8*1024*1024)
          throw new Error('Choose PNG, JPEG or WebP images up to 8 MiB each.');
        notice('Importing '+file.name+'…');
        const url=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=()=>reject(new Error('Could not read '+file.name));reader.readAsDataURL(file);});
        await rpc('import',{images:[{name:file.name,url}]});
      }
      await refresh();
    } catch(error){notice(error.message+' Any images already imported were kept.');}
    finally{control.disabled=false;}
  }
  function init(config) {
    options=config;
    el('gallery-button').onclick=()=>{
      if(!el('gallery-panel').hidden){close(true);return;}
      options.beforeOpen();el('gallery-panel').hidden=false;
      el('gallery-button').setAttribute('aria-expanded','true');
      el('gallery-search').focus();query=el('gallery-search').value.trim();refresh();
    };
    el('gallery-close').onclick=()=>close(true);
    let searchTimer;
    el('gallery-search').oninput=()=>{clearTimeout(searchTimer);revision++;searchTimer=setTimeout(()=>{query=el('gallery-search').value.trim();refresh();},200);};
    el('gallery-refresh').onclick=()=>refresh();
    el('gallery-more').onclick=()=>{if(nextOffset!=null)refresh(nextOffset);};
    el('gallery-folder').onclick=()=>rpc('openFolder').catch(error=>notice(error.message));
    el('gallery-import').onclick=()=>el('gallery-files').click();
    el('gallery-files').onchange=event=>{const files=Array.from(event.target.files||[]);event.target.value='';importFiles(files);};
    document.addEventListener('keydown',event=>{if(event.key==='Escape' && el('image-viewer').open!==true && !el('gallery-panel').hidden){close(true);}});
    document.addEventListener('click',event=>{if(!el('gallery-panel').hidden && !event.target.closest('#gallery-panel, #gallery-button, #image-viewer'))close();});
  }
  return {init,receive,close};
})();
