"""
spin_serial.py — serial-wise forced XI as requested:
 1 Rohit Sharma
 2 Sachin Tendulkar
 3 Virat Kohli
 4 Viv Richards
 5 AB de Villiers
 6 Heinrich Klaasen (carles → Klaasen, freq P6 leader)
 7 Shahid Afridi
 8 Wasim Akram
 9 Rashid Khan
10 Malcolm Marshall
11 Muttiah Muralitharan

Fallback mode STRATEGY=stat :
 1-3 highest BAT, 4-7 highest POW, 8-11 highest BWL (slot-specific)
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright
sys.stdout=open(sys.stdout.fileno(),mode="w",encoding="utf-8",buffering=1)
BASE_URL="https://500-0.com"
SHOTS_DIR=Path(__file__).parent/"shots_hack"; SHOTS_DIR.mkdir(exist_ok=True)
HANDLE=os.getenv("HANDLE","kunjan1387")
MAX_DRAFTS=int(os.getenv("MAX_DRAFTS","10"))
HOLD_SEC=int(os.getenv("HOLD_SEC","20"))
STRATEGY=os.getenv("STRATEGY","serial")  # serial or stat

# Serial XI — user request: Sachin/Virat/Viv/AB/Klaasen/Buttler/Afridi/Wasim/Malcolm/Shane/Murali (no Rohit)
SERIAL_XI = [
    (1, "Rohit Sharma"),
    (2, "Sachin Tendulkar"),  # 2000 B95
    (3, "Virat Kohli"),
    (4, "Viv Richards"),
    (5, "AB de Villiers"),
    (6, "Heinrich Klaasen"),
    (7, "Shahid Afridi"),
    (8, "Wasim Akram"),
    (9, "Shane Warne"),
    (10, "Malcolm Marshall"),
    (11, "Muttiah Muralitharan"),
]
# Alternative pure stat slots (user's second request): 1-3 BAT, 4-7 POW, 8-11 BWL
# kept as STRATEGY=stat_simple mode below
# For stat mode: slot ranges
def stat_for_slot(slot, p):
    # p = {b,p,bl}
    if 1 <= slot <= 3:
        return p.get("b",0)  # highest BAT
    if 4 <= slot <= 7:
        return p.get("p",0)  # highest POW
    if 8 <= slot <= 11:
        return p.get("bl",0) # highest BWL
    return 0

FREQ_JSON=json.dumps({"_":"_"}) # placeholder not needed but inject

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

async def setup_route(page):
    # capture seed sid for manual submit fallback
    async def seed_cap(route):
        resp=await route.fetch()
        try:
            txt=await resp.text()
            # store sid globally: response is {sid, seed}
            try:
                import json as _js
                data=_js.loads(txt)
                if "sid" in data:
                    await page.evaluate(f"() => {{ window.__lastSid='{data.get('sid','')}' ; window.__lastSeed='{data.get('seed','')}' }}")
                    log(f"  [SEED] sid={data.get('sid','')[:12]}.. seed={str(data.get('seed',''))[:8]}")
            except: pass
            await route.fulfill(response=resp, body=txt, content_type=resp.headers.get("content-type","application/json"))
        except:
            await route.continue_()
    await page.route("**/*raasnhafiz.workers.dev/seed*", seed_cap)
    async def lb_log(route):
        req=route.request
        try: body=req.post_data or ""
        except: body=""
        log(f"  [LB REQ] {req.method} {req.url[:140]} body={body[:300]}")
        resp=await route.fetch()
        try:
            txt=await resp.text()
            log(f"  [LB RESP] {resp.status} {txt[:600]}")
            await route.fulfill(response=resp, body=txt, content_type=resp.headers.get("content-type","application/json"))
        except Exception as e:
            log(f"  [LB ERR] {e}")
            await route.continue_()
    await page.route("**/*raasnhafiz.workers.dev/submit*", lb_log)
    await page.route("**/*raasnhafiz.workers.dev/board*", lb_log)
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
 const _orig=Math.random; let _s=RAND_SEED;
 function _prng(){_s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296;}
 window.__h={on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}, targetName:null};
 window.__reseed=(s)=>{_s=s|0;};
 Math.random=function(){const h=window.__h; if(!h.on) return _orig(); if(h.overrideReady&&h.idx>=0){const sz=(window.__gamePool||[]).length||h.poolSz; const v=(h.idx+0.5)/sz; h.idx=-1; h.overrideReady=false; return Math.min(Math.max(v,1e-6),0.999999);} return _prng();};
 // serial chooser: given desired player name, find pool team containing that player that fits desired slot
 window.__chooseTeamSerial = function(desiredName, desiredSlot){
   const vo=window.__vo, h=window.__h; if(!vo||!h) return null;
   const picked=new Set(h.picked.map(x=>x.name)); const K2=window.__K2||2;
   const pool=vo.filter(t=>{
     if(!t.players.some(p=>!picked.has(p.n) && h.openSlots.some(s=>s>=p.r[0]&&s<=p.r[1]))) return false;
     if((h.usage[t.id]||0)>=K2) return false; return true;
   });
   if(!pool.length) return null;
   const want = desiredName.trim().toLowerCase();
   // special: Sachin → force india_2000s (highest BAT 95 as requested)
   const wantSachin = want.includes("sachin");
   let candidates=[];
   pool.forEach((t,i)=>{
     const has = t.players.some(p=> p.n.toLowerCase()===want && !picked.has(p.n) && p.r[0]<=desiredSlot && desiredSlot<=p.r[1]);
     if(has) candidates.push({t,i});
     else {
       const has2 = t.players.some(p=> p.n.toLowerCase().includes(want) && !picked.has(p.n) && p.r[0]<=desiredSlot && desiredSlot<=p.r[1]);
       if(has2) candidates.push({t,i});
     }
   });
   if(candidates.length){
     candidates.sort((a,b)=>{
       // Sachin: prefer india_2000s (B95) as requested
       if(wantSachin){ // prefer 1990 as requested
         const want1990=true;
         const aIs2000 = (a.t.season||"").includes("1990") || (a.t.id||"").includes("1990");
         const bIs2000 = (b.t.season||"").includes("1990") || (b.t.id||"").includes("1990");
         if(aIs2000 && !bIs2000) return -1;
         if(!aIs2000 && bIs2000) return 1;
       }
       const pa=a.t.players.find(p=>p.n.toLowerCase()===want || p.n.toLowerCase().includes(want));
       const pb=b.t.players.find(p=>p.n.toLowerCase()===want || p.n.toLowerCase().includes(want));
       if(!pa||!pb) return 0;
       // for Sachin sort by BAT+POW, otherwise by total
       if(wantSachin) return (pb.b+pb.p)-(pa.b+pa.p);
       return (pb.b+pb.p+pb.bl)-(pa.b+pa.p+pa.bl);
     });
     const c=candidates[0];
     return {idx:c.i, poolSize:pool.length, team:c.t.name+" "+c.t.season, score:999};
   }
   return null;
 };
 window.__chooseTeamStat = function(desiredSlot){
   const vo=window.__vo, h=window.__h; if(!vo||!h) return null;
   const picked=new Set(h.picked.map(x=>x.name)); const K2=window.__K2||2;
   const pool=vo.filter(t=>{
     if(!t.players.some(p=>!picked.has(p.n) && p.r[0]<=desiredSlot && desiredSlot<=p.r[1])) return false;
     if((h.usage[t.id]||0)>=K2) return false; return true;
   });
   if(!pool.length) return null;
   function slotStat(p, slot){
     if(slot>=1&&slot<=3) return p.b;          // 1-3 BAT
     if(slot>=4&&slot<=7) return p.p;          // 4-7 POW
     if(slot>=8&&slot<=11) return p.bl;        // 8-11 BWL
     return 0;
   }
   let bestI=-1, bestS=-1, bestN="";
   pool.forEach((t,i)=>{
     let ms=-1;
     for(const p of t.players){
       if(picked.has(p.n)) continue;
       if(p.r[0]<=desiredSlot && desiredSlot<=p.r[1]){
         const s=slotStat(p, desiredSlot);
         // for Sachin, prefer highest BAT+POW variant if names equal
         const tie = p.b + p.p;
         const cur = ms + (ms>=0?0:0);
         if(s>ms) ms=s;
       }
     }
     if(ms>bestS){bestS=ms; bestI=i; bestN=t.name+" "+t.season;}
   });
   if(bestI<0) return null;
   return {idx:bestI, poolSize:pool.length, team:bestN, score:bestS};
 };
 // Sachin highest BAT+POW helper: choose best Sachin variant by b+p
 window.__pickBestSachin = function(cards){
   const sachins=cards.filter(c=>c.name.toLowerCase().includes("sachin"));
   if(!sachins.length) return null;
   sachins.sort((a,b)=>(b.b+b.p)-(a.b+a.p));
   return sachins[0];
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

async def ensure_hack(page, seed=None):
    try: has=await page.evaluate("() => !!window.__h && !!window.__vo && !!window.__chooseTeamSerial && !!window.__readCards")
    except: has=False
    if not has:
        for _ in range(12):
            try:
                if await page.evaluate("() => !!window.__vo"): break
            except: pass
            await page.wait_for_timeout(600)
        s=seed or random.randint(1,2**31-1)
        js=INJECT.replace("RAND_SEED",str(s))
        try: await page.evaluate(js)
        except: pass
        log(f"  (re-injected hack seed={s})"); await page.wait_for_timeout(900)
        # verify
        try:
            ok=await page.evaluate("() => !!window.__readCards")
            if not ok: log("  re-inject failed still no __readCards")
        except: pass

best_overs=[999]
async def one_draft(page, num):
    log(f"=== DRAFT #{num} [{STRATEGY}] ===")
    # wait for draft screen
    for _ in range(8):
        try:
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$",re.I)).first.is_visible(timeout=800): break
        except: pass
        await page.wait_for_timeout(500)
    await ensure_hack(page)
    new_seed=random.randint(1,2**31-1)
    try: await page.evaluate(f"() => window.__reseed({new_seed})")
    except: pass
    log(f"  seed={new_seed}")
    for attempt in range(4):
        try: await page.evaluate("() => { const h=window.__h; h.picked=[]; h.openSlots=[1,2,3,4,5,6,7,8,9,10,11]; h.usage={}; }"); break
        except Exception as e: log(f"  retry hack init {attempt+1}: {e}"); await ensure_hack(page, seed=new_seed); await page.wait_for_timeout(800)
    picks=[]
    # choose targets
    if STRATEGY=="serial":
        targets=SERIAL_XI
    else: # stat mode: generate targets per slot using stat logic (slot = position)
        targets=[(i, f"STAT_SLOT_{i}") for i in range(1,12)]

    for idx_slot, (slot, wantName) in enumerate(targets):
        # limit to 11 spins but allow re-spin if desired player not in pool (try up to 2 rerolls via next team)
        found=False
        for attempt in range(3):
            if STRATEGY=="serial":
                safeWant=json.dumps(wantName)
                result=await page.evaluate(f"() => window.__chooseTeamSerial({safeWant}, {slot})")
                mode=f"serial:{wantName} at {slot}"
            else:
                result=await page.evaluate(f"() => window.__chooseTeamStat({slot})")
                mode=f"stat slot {slot}"
            if result:
                log(f"  spin {len(picks)+1}: {result['team']} for {mode} idx={result['idx']}/{result['poolSize']}")
                await page.evaluate(f"() => {{ const h=window.__h; h.idx={result['idx']}; h.poolSz={result['poolSize']}; h.overrideReady=true; }}")
                spin_btn=page.locator("button").filter(has_text=re.compile(r"^SPIN$",re.I)).first
                if not await spin_btn.is_visible(timeout=3000):
                    log("  no SPIN"); break
                await spin_btn.click(timeout=5000); await page.wait_for_timeout(2500)
                try: sel=await page.evaluate("() => { const r=window.__lastSpinResult; return r?{id:r.id,name:r.name,season:r.season}:null; }")
                except: sel=None
                if sel:
                    try: await page.evaluate(f"() => {{ const h=window.__h; h.usage['{sel['id']}']=(h.usage['{sel['id']}']||0)+1; }}")
                    except: pass
                cards=await page.evaluate("() => window.__readCards()")
                if not cards: log("    no cards"); continue
                # pick desired card
                best=None
                if STRATEGY=="serial":
                    wantLower=wantName.lower()
                    # Sachin: pick variant with highest BAT+POW (user request)
                    if "sachin" in wantLower:
                        cands=[c for c in cards if "sachin" in c["name"].lower() and not c.get("disabled")]
                        if cands:
                            cands.sort(key=lambda x: x.get("b",0)+x.get("p",0), reverse=True)
                            best=cands[0]
                            log(f"    Sachin pick highest BAT+POW: {best['name']} B{best.get('b',0)} P{best.get('p',0)} sum={best.get('b',0)+best.get('p',0)}")
                    else:
                        for c in cards:
                            if c["name"].lower()==wantLower and not c.get("disabled"):
                                best=c; break
                        if not best:
                            for c in cards:
                                if wantLower in c["name"].lower() and not c.get("disabled"):
                                    best=c; break
                    if not best:
                        # fallback: stat best for this slot
                        scored=[]
                        for c in cards:
                            if c.get("disabled"): continue
                            s=stat_for_slot(slot, c)
                            scored.append((s,c))
                        if scored:
                            scored.sort(key=lambda x: x[0], reverse=True)
                            best=scored[0][1]
                            log(f"    desired {wantName} not in team, fallback to stat-best {best['name']} for slot {slot}")
                        else:
                            log(f"    no candidate for {wantName}, retrying spin")
                            continue
                else:
                    # stat mode: pick highest stat for slot among cards that fit slot
                    scored=[]
                    for c in cards:
                        if c.get("disabled"): continue
                        if not (c["lo"]<=slot<=c["hi"]): continue
                        s=stat_for_slot(slot, c)
                        scored.append((s,c))
                    # if none fit slot, pick any highest stat for slot
                    if not scored:
                        for c in cards:
                            if c.get("disabled"): continue
                            s=stat_for_slot(slot, c)
                            scored.append((s,c))
                    scored.sort(key=lambda x: x[0], reverse=True)
                    best=scored[0][1] if scored else None
                if not best:
                    log("    no best found"); continue
                log(f"    -> {best['name']} ({best['role']} B{best.get('b',0)} P{best.get('p',0)} BL{best.get('bl',0)}) want {wantName} slot {slot}")
                btns=page.locator("button"); await btns.nth(best["btnIdx"]).click(timeout=3000); await page.wait_for_timeout(1000)
                # position popup: click desired slot if available
                digits=await page.evaluate(r"""() => {
                    const dlg=[...document.querySelectorAll('div')].find(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||'')&&d.querySelector('button'));
                    const root=dlg||document; const out=[];
                    for(const b of root.querySelectorAll('button')){const t=(b.textContent||'').trim(); if(/^\d{1,2}$/.test(t)){const st=b.getAttribute('style')||''; const om=st.match(/opacity:\s*([\d.]+)/); out.push({n:parseInt(t), dis:!!b.disabled, op: om?parseFloat(om[1]):1});}}
                    return out;
                }""")
                if digits:
                    usable=[d["n"] for d in digits if not d["dis"] and d["op"]>0.85]
                    if usable:
                        chosen=slot if slot in usable else usable[0]
                        log(f"       pos: choosing {chosen} among {usable} (want {slot})")
                        await page.evaluate(f"""() => {{
                            const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                            const roots=dlgs.length?dlgs:[document];
                            for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{chosen}'&&!b.disabled){{b.click();return;}}
                        }}""")
                        await page.wait_for_timeout(500)
                picks.append({"name":best["name"],"slot":slot,"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0)})
                safe=best["name"].replace("'","\\'")
                await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{safe}'}}); const idx=h.openSlots.indexOf({slot}); if(idx>=0) h.openSlots.splice(idx,1); else if(h.openSlots.length) h.openSlots.shift(); }}")
                found=True
                break
            else:
                log(f"  no team for {wantName} slot {slot}, trying fallback stat")
                # fallback: try stat team
                result2=await page.evaluate(f"() => window.__chooseTeamStat({slot})")
                if result2:
                    log(f"  fallback stat team {result2['team']}")
                    # retry with stat team by forcing desiredName to empty? Just use stat team directly
                    # we can treat as serial miss and use stat team's best card
                    # Instead, force spin to stat team
                    await page.evaluate(f"() => {{ const h=window.__h; h.idx={result2['idx']}; h.poolSz={result2['poolSize']}; h.overrideReady=true; }}")
                    spin_btn=page.locator("button").filter(has_text=re.compile(r"^SPIN$",re.I)).first
                    if await spin_btn.is_visible(timeout=3000):
                        await spin_btn.click(timeout=5000); await page.wait_for_timeout(2500)
                        cards=await page.evaluate("() => window.__readCards()")
                        # pick best stat for slot
                        scored=[]
                        for c in cards:
                            if c.get("disabled"): continue
                            s=stat_for_slot(slot,c)
                            scored.append((s,c))
                        scored.sort(key=lambda x: x[0], reverse=True)
                        if scored:
                            best=scored[0][1]
                            log(f"    fallback stat pick {best['name']} for slot {slot}")
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
                                    chosen=slot if slot in usable else usable[0]
                                    await page.evaluate(f"""() => {{
                                        const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                                        const roots=dlgs.length?dlgs:[document];
                                        for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{chosen}'&&!b.disabled){{b.click();return;}}
                                    }}""")
                                    await page.wait_for_timeout(500)
                            picks.append({"name":best["name"],"slot":slot,"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0)})
                            safe=best["name"].replace("'","\\'")
                            await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{safe}'}}); const idx=h.openSlots.indexOf({slot}); if(idx>=0) h.openSlots.splice(idx,1); else if(h.openSlots.length) h.openSlots.shift(); }}")
                            found=True
                            break
                log(f"  failed to get {wantName}")
                break
        if not found:
            log(f"  skip slot {slot} {wantName} after attempts")
        if len(picks)>=11: break
    log(f"  Draft picks: {[(p['slot'],p['name']) for p in picks]}")
    for p in picks: log(f"    {p['slot']}: {p['name']} B{p['b']} P{p['p']} BL{p['bl']}")
    log("  Simulating...")
    sim=page.locator("button").filter(has_text=re.compile(r"SIMULATE",re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000); await page.wait_for_timeout(2000)
        skip=page.locator("button").filter(has_text=re.compile(r"SKIP TO END",re.I)).first
        try:
            if await skip.is_visible(timeout=3000): await skip.click(timeout=3000)
        except: pass
        await page.wait_for_timeout(3000)
    await page.screenshot(path=str(SHOTS_DIR/f"serial_d{num}.png"), full_page=False)
    body=await page.inner_text("body")
    overs_m=re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val=float(overs_m.group(1)) if overs_m else None
    if overs_val and "HISTORY REWRITTEN" in body:
        if overs_val < best_overs[0]: best_overs[0]=overs_val; log(f"  *** NEW BEST SERIAL OVERS: {overs_val} ***")
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
        try: await page.screenshot(path=str(SHOTS_DIR/f"serial_d{num}_win_hold.png"), full_page=True)
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
    strat = "serial Serial XI: " + ", ".join([f"{s}:{n}" for s,n in SERIAL_XI])
    log(f"spin_serial.py — HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} {strat}")
    log(f"Alternative stat: 1-3 BAT, 4-7 POW, 8-11 BWL")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx=await browser.new_context(viewport={"width":480,"height":1000}, device_scale_factor=2)
        page=await ctx.new_page()
        await setup_route(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        # FIX: use single fixed PID so all 500s stack under one leaderboard entry (otherwise 7+6+4 split)
        # PID is stored as five-hundred-pid, generated by Ga() if missing
        FIXED_PID = "k1387-" + HANDLE  # deterministic per handle, e.g. k1387-kunjan1387
        await page.evaluate(f"() => {{ localStorage.setItem('five-hundred-handle','{HANDLE}'); localStorage.setItem('five-hundred-pid','{FIXED_PID}'); }}")
        log(f"Fixed PID={FIXED_PID} for handle={HANDLE} (prevents split 7/6/4) ")
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
            # check leaderboard every 10 wins or every 10 drafts
            if wins>0 and wins%10==0:
                try:
                    pid=await page.evaluate("()=>localStorage.getItem('five-hundred-pid')")
                    for win in ["today","week","club","alltime"]:
                        try:
                            txt=await page.evaluate(f"async (w)=>{{ try{{ const r=await fetch('https://500leaderboard.raasnhafiz.workers.dev/board?window='+w+'&id='+encodeURIComponent(localStorage.getItem('five-hundred-pid'))); const j=await r.json(); return JSON.stringify(j).slice(0,900); }}catch(e){{return 'err '+e}} }}", win)
                            log(f"BOARD {win} after {wins} wins pid={pid[:8]}: {txt[:500]}")
                        except Exception as e:
                            log(f"board fetch {win} err {e}")
                        await page.wait_for_timeout(400)
                except Exception as e:
                    log(f"board check err {e}")
        log(f"=== DONE {wins}/{MAX_DRAFTS} wins best {best_overs[0]} overs ===")
        await page.wait_for_timeout(3000); await browser.close()
if __name__=="__main__": asyncio.run(main())
