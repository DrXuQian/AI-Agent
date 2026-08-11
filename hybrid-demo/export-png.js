const {chromium}=require('/opt/node22/lib/node_modules/playwright/index.js');
(async()=>{
  const b=await chromium.launch({executablePath:'/opt/pw-browsers/chromium'});
  // 1920x1080, 2x device scale for crisp export
  const p=await b.newPage({viewport:{width:1920,height:1080},deviceScaleFactor:2,colorScheme:'light'});
  await p.goto('file://'+__dirname+'/preview.html');
  await p.waitForTimeout(1500);
  const slides=await p.$$('.slide');
  const titles=await p.evaluate(()=>Array.prototype.map.call(document.querySelectorAll('.slide'),s=>s.dataset.title));
  await p.addStyleTag({content:'.rail,.counter,.hint{display:none!important}'});
  for(let i=0;i<slides.length;i++){
    await slides[i].scrollIntoViewIfNeeded();
    await p.waitForTimeout(500);
    const n=String(i+1).padStart(2,'0');
    await slides[i].screenshot({path:`png/${n}-${titles[i]}.png`});
  }
  await b.close();
  console.log('exported', slides.length);
})().catch(e=>{console.error(e.message);process.exit(1)});
