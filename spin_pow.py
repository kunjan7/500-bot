"""
spin_pow.py — POW-optimized strategy per user request:
  1-7  max POW
  1-5  max BAT+POW
  8-11 max BWL
  7-9  max POW+BWL
Also tries other promising combos via reasoning.
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright
sys.stdout=open(sys.stdout.fileno(),mode="w",encoding="utf-8",buffering=1)
BASE_URL="https://500-0.com"
SHOTS_DIR=Path(__file__).parent/"shots_hack"; SHOTS_DIR.mkdir(exist_ok=True)
HANDLE=os.getenv("HANDLE","kunjan1387")
MAX_DRAFTS=int(os.getenv("MAX_DRAFTS","50"))
HOLD_SEC=int(os.getenv("HOLD_SEC","20"))
STRATEGY=os.getenv("STRATEGY","pow")  # pow | hybrid | explore

FREQ_PATH=Path(__file__).parent/"freq_map.json"
with open(FREQ_PATH,encoding="utf-8") as f:_FM=json.load(f)
FREQ=_FM["freq_under40"]
COMB={}
for k,v in _FM["freq_top100"].items(): COMB[k]=v
for k,v in _FM["freq_under40"].items(): COMB[k]=max(v*2, COMB.get(k,0))
FREQ_JSON=json.dumps(COMB)

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}",flush=True)

async def setup_route(page):
    async def intercept(route):
        resp=await route.fetch(); body=await resp.text()
        if "window.__f6" not in body:
            body=body.replace("analysis:Z}}var Mc=","analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc=")
            body=body.replace("];function c6(){","];window.__vo=vo;window.__K2=K2;function c6(){")
            body=body.replace("Mt[Math.floor(Math.random()*Mt.length)]","(window.__gamePool=Mt,window.__lastSpinResult=Mt[Math.floor(Math.random()*Mt.length)])")
        await route.fulfill(response=resp, body=body, content_type="application/javascript")
    await page.route("**/*app*.js", intercept)

INJECT=r"""
(() => {
 if(window.__hackReady) return; window.__hackReady=true;
 const _orig=Math.random; let _s=SEED;
 function _prng(){_s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296;}
 window.__h={on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}, explore:false};
 window.__reseed=(s)=>{_s=s|0;}; window.__setExplore=(v)=>{window.__h.explore=!!v;};
 Math.random=function(){const h=window.__h; if(!h.on) return _orig(); if(h.overrideReady&&h.idx>=0){const sz=(window.__gamePool||[]).length||h.poolSz; const v=(h.idx+0.5)/sz; h.idx=-1; h.overrideReady=false; return Math.min(Math.max(v,1e-6),0.999999);} return _prng();};
 window.__FREQ=FREQ_JSON_PLACEHOLDER;
 // slot strategy weights: 1-5 BAT+POW, 1-7 POW, 8-11 BWL, 7-9 POW+BWL
 function slotScore(p, slot){
   // p: {b,p,bl}, slot 1..11
   let s=0;
   if(slot>=1 && slot<=5) s += (p.b + p.p)*1.0;      // BAT+POW 1-5
   if(slot>=1 && slot<=7) s += p.p*0.9;               // POW 1-7
   if(slot>=8 && slot<=11) s += p.bl*1.4;             // BWL 8-11 (heaviest)
   if(slot>=7 && slot<=9) s += (p.p + p.bl)*0.7;      // POW+BWL 7-9
   // hybrid bonus: freq for tie-break
   s += (window.__FREQ[p.n]||0)*0.15;
   return s;
 }
 window.__chooseTeamPow = function(){
   const vo=window.__vo, h=window.__h; if(!vo||!h) return null;
   const picked=new Set(h.picked.map(x=>x.name)); const slots=[...h.openSlots]; const K2=window.__K2||2;
   const pool=vo.filter(t=>{
     if(!t.players.some(p=>!picked.has(p.n) && slots.some(s=>s>=p.r[0]&&s<=p.r[1]))) return false;
     if((h.usage[t.id]||0)>=K2) return false; return true;
   });
   if(!pool.length) return null;
   function teamScore(team){
     let best=0, sum=0;
     for(const p of team.players){
       if(picked.has(p.n)) continue;
       // best slot this player can fill
       let ms=-1;
       for(const sl of slots){ if(sl>=p.r[0]&&sl<=p.r[1]){ const sc=slotScore(p, sl); if(sc>ms) ms=sc; } }
       if(ms<0) continue;
       sum += ms;
       if(ms>best) best=ms;
     }
     return sum*0.7 + best*0.3; // balance depth vs peak
   }
   const ranked=pool.map((t,i)=>({t,i,s:teamScore(t)})).sort((a,b)=>b.s-a.s);
   let choice=ranked[0];
   if(window.__h.explore && ranked.length>1 && _prng()<0.30){
     const r=_prng(); if(r<0.6) choice=ranked[1]; else if(ranked.length>2) choice=ranked[2];
   }
   return {idx:choice.i, poolSize:pool.length, team:choice.t.name+" "+choice.t.season, score:Math.round(choice.s)};
 };
 window.__readCards=function(){
   const out=[]; const seen=new Set();
   for(const b of document.querySelectorAll('button')){
     const t=b.innerText||''; if(!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue; if(!/BAT/.test(t)) continue;
     const st=b.getAttribute('style')||''; const om=st.match(/opacity:\s*([\d.]+)/); if(om&&parseFloat(om[1])<0.85) continue;
     const lines=t.split('\n').map(s=>s.trim()).filter(Boolean);
     let name=null, role='', lo=1, hi=11, bb=0, pp=0, bl=0;
     for(let i=0;i<lines.length;i++){const L=lines[i]; if(/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)){role=L.toUpperCase(); continue;} const rm=L.match(/^(\d{1,2})[-\u2013](\d{1,2})$/); if(rm){lo=+rm[1]; hi=+rm[2]; continue;} if(/^BAT$/i.test(L)&&i>0&&/^\d+$/.test(lines[i-1])){bb=+lines[i-1]; continue;} if(/^POW$/i.test(L)&&i>0&&/^\d+$/.test(lines[i-1])){pp=+lines[i-1]; continue;} if(/^BWL$/i.test(L)&&i>0&&/^\d+$/.test(lines[i-1])){bl=+lines[i-1]; continue;}}
     if(!name){for(const L of lines){if(/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) continue; if(/^\d/.test(L)) continue; if(/^(BAT|POW|BWL)$/i.test(L)) continue; name=L; break;}}
     if(!name||!role) continue; if(seen.has(name)) continue; seen.add(name);
     const disabled=b.disabled||getComputedStyle(b).opacity<0.5;
     out.push({name, role, disabled, b:bb, p:pp, bl, lo, hi});
   }
   const allBtns=document.querySelectorAll('button'); out.forEach(c=>{for(let i=0;i<allBtns.length;i++){if(allBtns[i].innerText&&allBtns[i].innerText.includes(c.name)){c.btnIdx=i; break;}}});
   return out;
 };
})();
"""
INJECT=INJECT.replace("SEED","RAND_SEED").replace("FREQ_JSON_PLACEHOLDER",FREQ_JSON)
best_overs=[999]
async def ensure_hack(page, seed=None):
    try: has=await page.evaluate("() => !!window.__h && !!window.__vo && !!window.__chooseTeamPow")
    except: has=False
    if not has:
        for _ in range(10):
            try:
                if await page.evaluate("() => !!window.__vo"): break
            except: pass
            await page.wait_for_timeout(500)
        s=seed or random.randint(1,2**31-1)
        js=INJECT.replace("RAND_SEED",str(s))
        try: await page.evaluate(js)
        except: pass
        log(f"  (re-injected hack seed={s})"); await page.wait_for_timeout(700)

async def one_draft(page, num):
    log(f"=== DRAFT #{num} [{STRATEGY}] ===")
    for _ in range(8):
        try:
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$",re.I)).first.is_visible(timeout=800): break
        except: pass
        await page.wait_for_timeout(500)
    await ensure_hack(page)
    new_seed=random.randint(1,2**31-1)
    try: await page.evaluate(f"() => window.__reseed({new_seed})")
    except: pass
    try: await page.evaluate(f"() => window.__setExplore(true)")
    except: pass
    log(f"  seed={new_seed}")
    for attempt in range(4):
        try: await page.evaluate("() => { const h=window.__h; h.picked=[]; h.openSlots=[1,2,3,4,5,6,7,8,9,10,11]; h.usage={}; }"); break
        except Exception as e: log(f"  retry hack init {attempt+1}: {e}"); await ensure_hack(page, seed=new_seed); await page.wait_for_timeout(800)
    picks=[]
    for spin in range(15):
        result=await page.evaluate("() => window.__chooseTeamPow()")
        if not result: log(f"  spin {spin+1}: empty pool"); break
        idx=result["idx"]; psz=result["poolSize"]
        log(f"  spin {spin+1}: {result['team']} powScore={result['score']} idx={idx}/{psz}")
        await page.evaluate(f"() => {{ const h=window.__h; h.idx={idx}; h.poolSz={psz}; h.overrideReady=true; }}")
        spin_btn=page.locator("button").filter(has_text=re.compile(r"^SPIN$",re.I)).first
        if not await spin_btn.is_visible(timeout=3000): log("  no SPIN"); break
        await spin_btn.click(timeout=5000); await page.wait_for_timeout(2500)
        try: sel=await page.evaluate("() => { const r=window.__lastSpinResult; return r?{id:r.id,name:r.name,season:r.season}:null; }")
        except: sel=None
        if sel:
            tid=sel["id"]
            try: await page.evaluate(f"() => {{ const h=window.__h; h.usage['{tid}']=(h.usage['{tid}']||0)+1; }}")
            except: pass
        cards=await page.evaluate("() => window.__readCards()")
        if not cards: log("    no cards"); continue
        # POW-strategy card scoring: best slot-specific score
        scored=[]
        # need openSlots snapshot
        open_slots=await page.evaluate("() => [...window.__h.openSlots]")
        for c in cards:
            if c.get("disabled"): continue
            # find best slot for this card among open_slots that it can fill
            best=-1; bestSlot=None
            for sl in open_slots:
                if sl>=c["lo"] and sl<=c["hi"]:
                    s=0
                    if 1<=sl<=5: s+=(c.get("b",0)+c.get("p",0))*1.0
                    if 1<=sl<=7: s+=c.get("p",0)*0.9
                    if 8<=sl<=11: s+=c.get("bl",0)*1.4
                    if 7<=sl<=9: s+=(c.get("p",0)+c.get("bl",0))*0.7
                    s+=(COMB.get(c["name"],0)*0.15)
                    if s>best: best=s; bestSlot=sl
            if best<0: best=c.get("b",0)+c.get("p",0)+c.get("bl",0)
            scored.append((best, COMB.get(c["name"],0), c, bestSlot))
        scored.sort(key=lambda x: x[0], reverse=True)
        if not scored: continue
        best=scored[0][2]; bestSlot=scored[0][3]
        log(f"    -> {best['name']} ({best['role']} B{best.get('b',0)} P{best.get('p',0)} BL{best.get('bl',0)}) slot {bestSlot} powScore={int(scored[0][0])} freq={scored[0][1]}")
        alts=", ".join([f"{c['name']}({int(s)})" for s,_,c,_ in scored[:3]])
        log(f"       candidates: {alts}")
        btns=page.locator("button"); await btns.nth(best["btnIdx"]).click(timeout=3000); await page.wait_for_timeout(1000)
        digits=await page.evaluate(r"""() => {
            const dlg=[...document.querySelectorAll('div')].find(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||'')&&d.querySelector('button'));
            const root=dlg||document; const out=[];
            for(const b of root.querySelectorAll('button')){const t=(b.textContent||'').trim(); if(/^\d{1,2}$/.test(t)){const st=b.getAttribute('style')||''; const om=st.match(/opacity:\s*([\d.]+)/); out.push({n:parseInt(t), dis:!!b.disabled, op: om?parseFloat(om[1]):1});}}
            return out;
        }""")
        if digits:
            usable=[d["n"] for d in digits if not d["dis"] and d["op"]>0.85]
            if usable:
                # choose the slot that gave best score, else freq-best
                chosen=bestSlot if bestSlot in usable else usable[0]
                log(f"       pos: choosing {chosen} among {usable}")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{chosen}'&&!b.disabled){{b.click();return;}}
                }}""")
                await page.wait_for_timeout(500)
        picks.append({"name":best["name"],"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0)})
        safe=best["name"].replace("'","\\'")
        await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{safe}'}}); if(h.openSlots.length) h.openSlots.shift(); }}")
        if len(picks)>=11: log("  All 11 picked!"); break
    # summary: compute POW/BAT+POW/BWL stats
    if picks:
        # fetch openSlots not needed, just log
        b_top = sorted([p["b"] for p in picks[:7]], reverse=True) if len(picks)>=7 else []
        p_top = sorted([p["p"] for p in picks[:7]], reverse=True) if len(picks)>=7 else []
    log(f"  Draft picks: {[p['name'] for p in picks]}")
    log("  Simulating...")
    sim=page.locator("button").filter(has_text=re.compile(r"SIMULATE",re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000); await page.wait_for_timeout(2000)
        skip=page.locator("button").filter(has_text=re.compile(r"SKIP TO END",re.I)).first
        try:
            if await skip.is_visible(timeout=3000): await skip.click(timeout=3000)
        except: pass
        await page.wait_for_timeout(3000)
    await page.screenshot(path=str(SHOTS_DIR/f"pow_d{num}.png"), full_page=False)
    body=await page.inner_text("body")
    overs_m=re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val=float(overs_m.group(1)) if overs_m else None
    if overs_val and "HISTORY REWRITTEN" in body:
        if overs_val < best_overs[0]: best_overs[0]=overs_val; log(f"  *** NEW BEST OVERS POW: {overs_val} ***")
        else: log(f"  overs {overs_val} best {best_overs[0]}")
    if "HISTORY REWRITTEN" in body:
        log("  >>> WIN! HISTORY REWRITTEN <<<")
        try:
            for _ in range(12):
                claim=page.locator("button").filter(has_text=re.compile(r"CLAIM MY SPOT",re.I)).first
                if await claim.is_visible(timeout=800):
                    inp=page.locator("input[placeholder='pick a handle']").first
                    try:
                        if await inp.is_visible(timeout=600):
                            v=await inp.input_value()
                            if not v or len(v.strip())<2: await inp.fill(HANDLE); await page.wait_for_timeout(300)
                    except: pass
                    await claim.click(timeout=2000); log("  clicked CLAIM MY SPOT"); await page.wait_for_timeout(2500); break
                await page.wait_for_timeout(500)
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        except Exception as e: log(f"  auto-claim err {e}")
        log(f"  HOLDING {HOLD_SEC}s then continue...")
        try: await page.wait_for_timeout(HOLD_SEC*1000)
        except: await asyncio.sleep(HOLD_SEC)
        try: await page.screenshot(path=str(SHOTS_DIR/f"pow_d{num}_win_hold.png"), full_page=True)
        except: pass
        again=page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN",re.I)).first
        try:
            if await again.is_visible(timeout=4000): await again.click(timeout=4000); await page.wait_for_timeout(2500)
        except: pass
        return True
    for kw in ["CHOKED","HEARTBREAK","OUTCLASSED","UNPREPARED"]:
        if kw in body: log(f"  Result: {kw}"); break
    m=re.search(r"(\d+/\d+)\s", body)
    if m: log(f"  Score: {m.group(1)}")
    again=page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN",re.I)).first
    try:
        if await again.is_visible(timeout=3000): await again.click(timeout=3000); await page.wait_for_timeout(2000)
    except: pass
    return False

async def main():
    log(f"spin_pow.py — HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} STRAT={STRATEGY}")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx=await browser.new_context(viewport={"width":480,"height":1000}, device_scale_factor=2)
        page=await ctx.new_page()
        await setup_route(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        ok_vo=await page.evaluate("() => !!window.__vo")
        log(f"Capture vo={ok_vo}")
        if not ok_vo: await browser.close(); return
        seed=random.randint(1,2**31-1)
        js=INJECT.replace("RAND_SEED",str(seed)); await page.evaluate(js); log(f"Hack injected seed={seed}")
        easy=page.locator("button").filter(has_text=re.compile(r"^EASY",re.I)).first
        await easy.click(timeout=3000); await page.wait_for_timeout(500)
        draft=page.locator("button").filter(has_text=re.compile(r"^DRAFT$",re.I)).first
        await draft.click(timeout=3000); await page.wait_for_timeout(2000)
        log("Entered draft")
        wins=0
        for i in range(1, MAX_DRAFTS+1):
            won=await one_draft(page,i)
            if won: wins+=1
        log(f"=== DONE {wins}/{MAX_DRAFTS} wins best {best_overs[0]} overs ===")
        await page.wait_for_timeout(3000); await browser.close()
if __name__=="__main__": asyncio.run(main())
