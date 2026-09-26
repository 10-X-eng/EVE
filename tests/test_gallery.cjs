// Real UI/async Fusion bridge coverage; no model calls or personal image data.
const assert=require('node:assert/strict');
const path=require('node:path');
const {pathToFileURL}=require('node:url');
const {chromium}=require('playwright');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:440,height:760}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      window.requests=[];
      const canvas=document.createElement('canvas');canvas.width=320;canvas.height=240;
      const c=canvas.getContext('2d');c.fillStyle='#263e36';c.fillRect(0,0,320,240);
      c.fillStyle='#aee0ce';c.fillRect(65,60,190,120);c.fillStyle='#263e36';c.fillRect(85,80,150,80);
      window.pixels=canvas.toDataURL('image/png');
      window.galleryRows=Array.from({length:23},(_,i)=>({imageId:i.toString(16).padStart(64,'0'),name:i===0?'Enclosure concept':`Reference ${i}`,enabled:false}));
      window.adsk={fusionSendData:async(action,raw)=>{
        const p=JSON.parse(raw);requests.push({action,payload:p});
        if(action!=='gallery')return JSON.stringify({ok:true});
        setTimeout(()=>{
          let result={ok:true};
          const row=galleryRows.find(row=>row.imageId===p.imageId);
          if(p.action==='list'){
            const filtered=galleryRows.filter(row=>row.name.toLowerCase().includes((p.query||'').toLowerCase()));
            const offset=p.offset||0;
            result={...result,images:filtered.slice(offset,offset+20),total:filtered.length,nextOffset:offset+20<filtered.length?offset+20:null};
          }else if(p.action==='asset')result={...result,image:{...row,url:pixels}};
          else if(p.action==='change')Object.assign(row,p.name?{name:p.name}:{enabled:p.enabled});
          else if(p.action==='remove')window.galleryRows=galleryRows.filter(item=>item.imageId!==p.imageId);
          else if(p.action==='import')galleryRows.push({imageId:'f'.repeat(64),name:p.images[0].name,enabled:false});
          window.fusionJavaScriptHandler.handle('gallery',JSON.stringify({requestId:p.requestId,...result}));
        },5);
        return JSON.stringify({ok:true,pending:true});
      }};
    });
    await page.goto(pathToFileURL(path.resolve(__dirname,'../addin/STEVE/panel/index.html')).href);
    await page.evaluate(()=>{
      window.snapshot={connection:'ready',account:{email:'Fixture'},provider:'chatgpt',accountChecked:true,
        models:[{id:'vision',supportsImages:true}],model:'vision',threadId:'one',messages:[],busy:false,status:'Ready'};
      window.sendState=()=>window.fusionJavaScriptHandler.handle('state',JSON.stringify(snapshot));sendState();
    });
    await page.getByRole('button',{name:'Image gallery',exact:true}).click();
    assert.equal(await page.locator('#gallery-button').getAttribute('aria-expanded'),'true');
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===20);
    await page.locator('.gallery-preview img').first().waitFor();
    assert.equal(await page.locator('.gallery-access input:checked').count(),0);
    await page.locator('#gallery-more').click();
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===23);
    assert.equal(await page.locator('#gallery-more').isVisible(),false);
    await page.locator('#gallery-search').fill('Enclosure');
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===1);
    const toggle=page.locator('.gallery-access input');
    await toggle.check();await page.waitForFunction(()=>galleryRows[0].enabled);
    await toggle.uncheck();await page.waitForFunction(()=>!galleryRows[0].enabled);
    const name=page.getByRole('textbox',{name:'Image name',exact:true});
    await name.fill('<img src=x onerror=alert(1)>');await name.press('Enter');
    await page.waitForFunction(()=>galleryRows[0].name.startsWith('<img'));
    assert.equal(await page.locator('.gallery-card img[onerror]').count(),0);
    await page.locator('.gallery-preview').click();
    await page.locator('#image-viewer').waitFor();await page.locator('#close-image').click();
    await page.locator('#message').evaluate(el=>{el.value='Keep this draft';});
    await page.getByRole('button',{name:'Attach',exact:true}).click();
    await page.waitForFunction(()=>document.querySelectorAll('#image-drafts .image-chip').length===1);
    assert.equal(await page.locator('#message').inputValue(),'Keep this draft');
    assert.equal(await page.locator('#gallery-panel').isVisible(),false);
    assert.equal(await page.evaluate(()=>requests.filter(r=>['send','steer'].includes(r.action)).length),0);
    await page.locator('#gallery-button').click();
    await page.locator('#gallery-search').fill('');
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===20);
    const png=await page.evaluate(()=>pixels.split(',')[1]);
    await page.locator('#gallery-files').setInputFiles({name:'Imported.png',mimeType:'image/png',buffer:Buffer.from(png,'base64')});
    await page.waitForFunction(()=>galleryRows.some(row=>row.name==='Imported.png'));
    assert.equal(await page.evaluate(()=>galleryRows.find(row=>row.name==='Imported.png').enabled),false);
    await page.locator('#gallery-search').fill('Imported');
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===1 && document.querySelector('.gallery-card input').value==='Imported.png');
    await page.getByRole('button',{name:'Remove',exact:true}).click();
    await page.waitForFunction(()=>document.getElementById('gallery-empty').hidden===false);
    await page.locator('#gallery-search').fill('');
    await page.waitForFunction(()=>document.querySelectorAll('.gallery-card').length===20);
    for(const width of [320,440,760]){
      await page.setViewportSize({width,height:650});
      assert(await page.locator('#gallery-panel .panel-body').evaluate(el=>el.scrollWidth<=el.clientWidth),`Gallery overflow at ${width}`);
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
    }
    await page.setViewportSize({width:440,height:760});
    if(process.env.STEVE_GALLERY_SCREENSHOT)await page.screenshot({path:process.env.STEVE_GALLERY_SCREENSHOT});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#gallery-panel').isVisible(),false);
    assert.equal(await page.locator('#gallery-button').getAttribute('aria-expanded'),'false');
    await page.evaluate(()=>{
      snapshot.releaseNotes={version:'0.8.0',title:'Shared images',items:['Browse the gallery.','<img src=x onerror=alert(1)>'],note:'Start a new chat for lookup tools.'};
      snapshot.releaseNotesUnread=true;sendState();
    });
    await page.locator('#release-notice').waitFor({state:'visible'});
    await page.locator('#show-release-notes').click();
    assert.equal(await page.locator('#release-notes-dialog').isVisible(),true);
    assert.equal(await page.locator('#release-notes-items li').count(),2);
    assert.equal(await page.locator('#release-notes-items img').count(),0);
    assert(await page.evaluate(()=>requests.some(r=>r.action==='acknowledgeReleaseNotes'&&r.payload.version==='0.8.0')));
    await page.locator('#close-release-notes').click();
    await page.evaluate(()=>{snapshot.releaseNotesUnread=false;sendState();});
    await page.locator('#release-notice').waitFor({state:'hidden'});
    // Notes remain reachable after dismissal without a network request.
    await page.locator('#installed-release-notes').evaluate(el=>el.click());
    assert.equal(await page.locator('#release-notes-dialog').isVisible(),true);
    await page.locator('#close-release-notes').click();
    assert.deepEqual(errors,[]);
    console.log('Gallery browser checks passed: async bridge, header dropdown, paging, search, access, rename, preview, attach, import, remove and narrow layouts.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
