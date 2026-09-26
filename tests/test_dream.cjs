// Real-browser coverage for native image events and concept refinement. Uses no model calls.
const assert = require('node:assert/strict');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async()=>{
  const browser=await chromium.launch({channel:'msedge',headless:true});
  try{
    const page=await browser.newPage({viewport:{width:440,height:760}});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    await page.addInitScript(()=>{
      window.requests=[];
      window.adsk={fusionSendData:async(action,raw)=>{
        const payload=JSON.parse(raw);window.requests.push({action,payload});
        if(action==='imageAssets')return JSON.stringify({ok:true,images:{concept:window.conceptPixels}});
        return JSON.stringify({ok:true,filename:'STEVE-concept.png'});
      }};
    });
    await page.goto(pathToFileURL(path.resolve(__dirname,'../addin/STEVE/panel/index.html')).href);
    await page.evaluate(()=>{
      // A valid PNG with trailing padding exercises previews larger than the attachment limit.
      const png=atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aMGQAAAAASUVORK5CYII=');
      window.conceptPixels='data:image/png;base64,'+btoa(png+'\0'.repeat(1100000));
      window.snapshot={connection:'ready',provider:'chatgpt',account:{email:'Test',planType:'Plus'},
        accountChecked:true,models:[{id:'fixture',supportsImages:true}],model:'fixture',threadId:'chat',
        messages:[],busy:false,loginPending:false,status:'Ready',error:''};
      window.update=()=>window.fusionJavaScriptHandler.handle('state',JSON.stringify(window.snapshot));
      window.update();
    });
    // Dream lives in the composer's + menu; choosing it closes the menu and starts a draft.
    await page.locator('#composer-plus').click();
    assert.equal(await page.locator('#plus-menu').isVisible(),true);
    await page.locator('#dream').click();
    assert.equal(await page.locator('#plus-menu').isVisible(),false);
    assert.match(await page.locator('#message').inputValue(),/Generate a concept image/);
    await page.locator('#message').fill('');
    await page.evaluate(()=>{
      snapshot.busy=true;snapshot.messages=[{id:'dream-1',role:'assistant',concept:true,
        conceptStatus:'running',text:'Dreaming…'}];update();
    });
    await page.locator('[data-concept-status="running"]').waitFor();
    await page.evaluate(()=>{
      window.originalCard=document.querySelector('#conversation article');
      snapshot.messages[0]={...snapshot.messages[0],conceptStatus:'completed',text:'Concept · Visual reference, not verified geometry.',
        images:[{id:'concept',name:'Enclosure concept',generated:true}]};snapshot.busy=false;update();
    });
    await page.waitForFunction(()=>document.querySelector('.concept-image img')?.naturalWidth>0);
    assert.ok(await page.evaluate(()=>originalCard===document.querySelector('#conversation article')));
    assert.equal(await page.locator('.concept-caption .dream-tag').textContent(),'✧ Dream');
    assert.equal(await page.locator('#conversation article .message-body').isVisible(),false,'A finished concept shows its picture, not the placeholder text');
    await page.evaluate(()=>{window.originalImage=document.querySelector('.concept-image img');snapshot.messages.push({id:'answer',role:'assistant',text:'A concept.'});update();});
    await page.waitForFunction(()=>document.querySelectorAll('#conversation article').length===2);
    assert.ok(await page.evaluate(()=>originalImage===document.querySelector('.concept-image img')));
    await page.getByRole('button',{name:'Refine',exact:true}).click();
    await page.waitForFunction(()=>document.getElementById('message').value==='Refine this concept: ');
    assert.equal(await page.locator('#image-drafts .image-chip').count(),1);
    const sendCount=await page.evaluate(()=>requests.filter(r=>r.action==='send').length);
    assert.equal(sendCount,0,'Choosing a concept must not submit or modify Fusion');
    // Existing drafts must survive attempts to choose another concept.
    await page.getByRole('button',{name:'Use as reference',exact:true}).click();
    assert.equal(await page.locator('#message').inputValue(),'Refine this concept: ');
    await page.getByRole('button',{name:'Save',exact:true}).click();
    await page.getByRole('button',{name:'Saved to Downloads'}).waitFor();
    assert.ok(await page.evaluate(()=>requests.some(r=>r.action==='saveConcept'&&r.payload.id==='concept')));
    await page.evaluate(()=>{snapshot.busy=true;update();});
    await page.waitForFunction(()=>document.querySelector('.concept-draft-action').disabled);
    await page.evaluate(()=>{snapshot.busy=false;snapshot.provider='ollama';snapshot.models=[{id:'fixture',supportsImages:false}];update();});
    await page.waitForFunction(()=>document.getElementById('dream-entry').hidden);
    assert.ok(await page.getByRole('button',{name:'Use as reference',exact:true}).isDisabled());
    assert.deepEqual(errors,[]);
    console.log('Dream checks passed: large previews, generation progress, retained DOM, reference preparation, draft protection, export and provider limits.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
