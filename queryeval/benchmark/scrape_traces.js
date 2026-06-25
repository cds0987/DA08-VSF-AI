// Scrape Langfuse span-trees for trace_ids in a results jsonl.
// Usage: NODE_PATH=<playwright> node scrape_traces.js <results.jsonl> <out.json>
const { chromium } = require('playwright');
const fs = require('fs'); const path = require('path');
const RESULTS = process.argv[2]; const OUT = process.argv[3]; const STATE = process.argv[4];
const LF = process.env.LF_URL || 'https://langfuse.vsfchat.cloud';
// Creds qua ENV (KHÔNG hardcode): LF_BASIC_USER/LF_BASIC_PW = nginx basic-auth; LF_EMAIL/LF_PW = app login.
const BASIC = { username: process.env.LF_BASIC_USER || '', password: process.env.LF_BASIC_PW || '' };

function parseDur(s){
  let m=s.match(/^(\d+)m\s+(\d+)s$/); if(m)return +m[1]*60+ +m[2];
  m=s.match(/^(\d+(?:\.\d+)?)s$/); if(m)return parseFloat(m[1]);
  m=s.match(/^(\d+)ms$/); if(m)return +m[1]/1000; return null;
}
(async()=>{
  const rows=fs.readFileSync(RESULTS,'utf8').trim().split('\n').map(l=>JSON.parse(l)).filter(r=>r.trace_id);
  console.log('traces:',rows.length);
  const b=await chromium.launch({headless:true});
  const ctxOpts={httpCredentials:BASIC,viewport:{width:1700,height:1300}};
  if(STATE && fs.existsSync(STATE)) ctxOpts.storageState=STATE;
  const c=await b.newContext(ctxOpts);
  const p=await c.newPage();
  async function ensureLogin(){
    if(STATE && fs.existsSync(STATE)){
      await p.goto(`${LF}/project/rag-chatbot`,{waitUntil:'domcontentloaded',timeout:60000});
      await p.waitForTimeout(1500);
      if(!p.url().includes('/auth/sign-in')) return true;
    }
    for(let attempt=0; attempt<4; attempt++){
      await p.goto(`${LF}/project/rag-chatbot`,{waitUntil:'networkidle',timeout:60000});
      await p.waitForTimeout(1500);
      if(!p.url().includes('/auth/sign-in') && await p.locator('input[type="email"]').count()===0) return true;
      if(await p.locator('input[type="email"]').count()){
        await p.fill('input[type="email"]', process.env.LF_EMAIL || '');
        await p.fill('input[type="password"]', process.env.LF_PW || '');
        // click the VISIBLE submit button (there are 2; one hidden)
        const btns=p.locator('button[type="submit"]');
        const n=await btns.count(); let clicked=false;
        for(let i=0;i<n;i++){ if(await btns.nth(i).isVisible()){ await btns.nth(i).click(); clicked=true; break; } }
        if(!clicked) await p.locator('input[type="password"]').press('Enter');
        await p.waitForLoadState('networkidle',{timeout:60000}).catch(()=>{});
        await p.waitForTimeout(3500);
      }
      if(!p.url().includes('/auth/sign-in')) return true;
    }
    return false;
  }
  const li=await ensureLogin();
  console.log('login ok:', li, '| url:', p.url());
  if(!li){ console.error('LOGIN FAILED'); process.exit(2); }
  const out=[];
  for(let i=0;i<rows.length;i++){
    const r=rows[i];
    try{
      await p.goto(`${LF}/project/rag-chatbot/traces/${r.trace_id}`,{waitUntil:'domcontentloaded',timeout:60000});
      await p.waitForTimeout(2300);
      const lns=(await p.evaluate(()=>document.body.innerText)).split('\n').map(s=>s.trim()).filter(Boolean);
      const nodes=[];
      for(let j=0;j<lns.length;j++){
        if(['SPAN','GENERATION','EVENT'].includes(lns[j])){
          const name=lns[j+1]||''; let dur=null;
          for(let k=j+2;k<Math.min(j+4,lns.length);k++){const d=parseDur(lns[k]);if(d!==null){dur=d;break;}}
          nodes.push({type:lns[j],name,dur});
        }
      }
      out.push({id:r.id,subtype:r.subtype,trace_id:r.trace_id,total_latency:r.total_latency,
                ttft:r.ttft,n_sources:r.n_sources,nodes});
      const work=nodes.filter(n=>['rag_search','rag_retrieve','hr_lookup','hr_query','leave_action','analyze'].includes(n.name)).length;
      if(i%10===0) console.log(`${i+1}/${rows.length} ${r.id} nodes=${nodes.length} work=${work}`);
    }catch(e){ out.push({id:r.id,trace_id:r.trace_id,error:e.message}); }
  }
  fs.writeFileSync(OUT,JSON.stringify(out,null,1));
  console.log('wrote',OUT,out.length);
  await b.close();
})().catch(e=>{console.error('FATAL',e);process.exit(1);});
