"""
spin_fixed11.py — fixed 11 for 500 win (infinite loop)
Forces XI: Rohit Sharma, Sachin Tendulkar, Virat Kohli, Viv Richards, AB de Villiers,
Heinrich Klaasen, Shahid Afridi, Wasim Akram, Malcolm Marshall, Shane Warne, Muttiah Muralitharan
Uses same spin hack as spin_freq but card picker prioritizes fixed XI in order 1..11.
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
SHOTS_DIR = Path(__file__).parent / "shots_hack"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "kunjan700")
MAX_DRAFTS = int(os.getenv("MAX_DRAFTS", "1000"))
HOLD_SEC = int(os.getenv("HOLD_SEC", "20"))

# Fixed 11 in draft order 1..11 (positions)
FIXED_XI = [
    (1, "Rohit Sharma"),
    (2, "Sachin Tendulkar"),
    (3, "Virat Kohli"),
    (4, "Viv Richards"),
    (5, "AB de Villiers"),
    (6, "Heinrich Klaasen"),
    (7, "Shahid Afridi"),
    (8, "Wasim Akram"),
    (9, "Malcolm Marshall"),
    (10, "Shane Warne"),
    (11, "Muttiah Muralitharan"),
]
FIXED_NAMES = [n for _,n in FIXED_XI]
FIXED_SET = set(FIXED_NAMES)

# For logging, load freq for reference
try:
    with open(Path(__file__).parent / "freq_map.json", encoding="utf-8") as f:
        FM=json.load(f)
        COMB={k:v for k,v in FM["freq_top100"].items()}
        for k,v in FM["freq_under40"].items():
            COMB[k]=max(v*2, COMB.get(k,0))
except:
    COMB={}

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

async def setup_route_interception(page):
    async def lb_log(route):
        req=route.request
        try: body=req.post_data or ""
        except: body=""
        log(f"  [LB REQ] {req.method} {req.url[:150]} body={body[:300]}")
        resp=await route.fetch()
        try:
            txt=await resp.text()
            log(f"  [LB RESP] {resp.status} {txt[:500]}")
            await route.fulfill(response=resp, body=txt, content_type=resp.headers.get("content-type","application/json"))
        except:
            await route.continue_()
    await page.route("**/*500leaderboard*submit*", lb_log)
    await page.route("**/*500leaderboard*board*", lb_log)
    await page.route("**/*raasnhafiz*workers.dev*submit*", lb_log)
    await page.route("**/*raasnhafiz*workers.dev*board*", lb_log)
    async def intercept(route):
        resp=await route.fetch()
        body=await resp.text()
        if "window.__f6" not in body:
            body=body.replace("analysis:Z}}var Mc=", "analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc=")
            body=body.replace("];function c6(){", "];window.__vo=vo;window.__K2=K2;function c6(){")
            body=body.replace("Mt[Math.floor(Math.random()*Mt.length)]","(window.__gamePool=Mt,window.__lastSpinResult=Mt[Math.floor(Math.random()*Mt.length)])")
        await route.fulfill(response=resp, body=body, content_type="application/javascript")
    await page.route("**/*app*.js", intercept)

INJECT_HACK_JS = r"""
(() => {
    if (window.__hackReady) return;
    window.__hackReady = true;
    const _orig = Math.random;
    let _s = SEED;
    function _prng(){ _s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }
    window.__h = { on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}, rerollTeam:null };
    window.__reseed = (s) => { _s = s|0; };
    Math.random = function(){
        const h=window.__h;
        if(!h.on) return _orig();
        if(h.overrideReady && h.idx>=0){
            const actualPoolSz=(window.__gamePool||[]).length||h.poolSz;
            const v=(h.idx+0.5)/actualPoolSz;
            h.idx=-1; h.overrideReady=false;
            return Math.min(Math.max(v,1e-6),0.999999);
        }
        return _prng();
    };
    // Fixed XI list injected
    window.__FIXED_XI = FIXED_JSON_PLACEHOLDER;
    window.__chooseTeamFixed = function(){
        const vo=window.__vo, h=window.__h;
        if(!vo||!h) return null;
        const picked=new Set(h.picked.map(p=>p.name));
        const slots=[...h.openSlots];
        const K2=window.__K2||2;
        // find next needed fixed player that fits an open slot
        let need=null;
        for(const name of window.__FIXED_XI){
            if(picked.has(name)) continue;
            // find if any team has this player fitting open slot
            need=name; break;
        }
        if(!need) return null;
        // filter teams that contain need and fit slot
        let pool=vo.filter(t=>{
            const hasNeed=t.players.some(p=>p.n===need && slots.some(s=>s>=p.r[0]&&s<=p.r[1]));
            if(!hasNeed) return false;
            if((h.usage[t.id]||0)>=K2) return false;
            return true;
        });
        // fallback: any team with any fixed remaining that fits
        if(!pool.length){
            pool=vo.filter(t=>{
                return t.players.some(p=> window.__FIXED_XI.includes(p.n) && !picked.has(p.n) && slots.some(s=>s>=p.r[0]&&s<=p.r[1]))
                    && (h.usage[t.id]||0)<K2;
            });
        }
        if(!pool.length) return null;
        // pick first (or random if multiple)
        const ranked=pool.map((t,i)=>({t,i})).sort((a,b)=> a.t.name.localeCompare(b.t.name));
        let choice=ranked[0];
        return {idx:choice.i, poolSize:pool.length, team:choice.t.name+" "+choice.t.season};
    };
    window.__chooseTeamFreq = window.__chooseTeamFixed;
    window.__readCards = function(){
        const out=[]; const seen=new Set();
        for(const b of document.querySelectorAll('button')){
            const t=b.innerText||'';
            if(!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue;
            if(!/BAT/.test(t)) continue;
            const st=b.getAttribute('style')||'';
            const om=st.match(/opacity:\s*([\d.]+)/);
            if(om && parseFloat(om[1])<0.85) continue;
            const lines=t.split('\n').map(s=>s.trim()).filter(Boolean);
            let name=null, role='', lo=1, hi=11, bb=0, pp=0, bl=0;
            for(let i=0;i<lines.length;i++){
                const L=lines[i];
                if(/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)){ role=L.toUpperCase(); continue; }
                const rm=L.match(/^(\d{1,2})[-\u2013](\d{1,2})$/);
                if(rm){ lo=+rm[1]; hi=+rm[2]; continue; }
                if(/^BAT$/i.test(L) && i>0 && /^\d+$/.test(lines[i-1])){ bb=+lines[i-1]; continue; }
                if(/^POW$/i.test(L) && i>0 && /^\d+$/.test(lines[i-1])){ pp=+lines[i-1]; continue; }
                if(/^BWL$/i.test(L) && i>0 && /^\d+$/.test(lines[i-1])){ bl=+lines[i-1]; continue; }
            }
            if(!name){ for(const L of lines){ if(/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) continue; if(/^\d/.test(L)) continue; if(/^(BAT|POW|BWL)$/i.test(L)) continue; name=L; break; } }
            if(!name||!role) continue;
            if(seen.has(name)) continue; seen.add(name);
            const disabled=b.disabled||getComputedStyle(b).opacity<0.5;
            out.push({name, role, disabled, b:bb, p:pp, bl, lo, hi});
        }
        const allBtns=document.querySelectorAll('button');
        out.forEach(c=>{ for(let i=0;i<allBtns.length;i++){ if(allBtns[i].innerText && allBtns[i].innerText.includes(c.name)){ c.btnIdx=i; break; } } });
        return out;
    };
})();
"""
INJECT_HACK_JS = INJECT_HACK_JS.replace("SEED", "RAND_SEED").replace("FIXED_JSON_PLACEHOLDER", json.dumps(FIXED_NAMES))

best_overs=[999]
best_balls=[999]

async def ensure_hack(page, seed=None):
    try:
        has=await page.evaluate("() => !!window.__h && !!window.__vo && !!window.__chooseTeamFixed")
    except:
        has=False
    if not has:
        for _ in range(10):
            try:
                if await page.evaluate("() => !!window.__vo"): break
            except: pass
            await page.wait_for_timeout(500)
        s=seed or random.randint(1,2**31-1)
        js=INJECT_HACK_JS.replace("RAND_SEED", str(s))
        try: await page.evaluate(js)
        except: pass
        log(f"  (re-injected hack seed={s})")
        await page.wait_for_timeout(700)

async def one_draft(page, num):
    log(f"=== DRAFT #{num} FIXED11 {HANDLE} ===")
    for _ in range(8):
        try:
            await page.wait_for_timeout(500)
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=800):
                break
        except: pass
    await ensure_hack(page)
    new_seed=random.randint(1,2**31-1)
    try: await page.evaluate(f"() => window.__reseed({new_seed})")
    except: pass
    log(f"  seed={new_seed}")
    try:
        await page.evaluate("() => { const h=window.__h; h.picked=[]; h.openSlots=[1,2,3,4,5,6,7,8,9,10,11]; h.usage={}; }")
    except:
        await ensure_hack(page, seed=new_seed)
    picks=[]
    # map position -> expected name
    pos_to_name = {pos:name for pos,name in FIXED_XI}
    for spin in range(15):
        # choose team containing next needed fixed player
        result=await page.evaluate("() => window.__chooseTeamFixed()")
        if not result:
            log(f"  spin {spin+1}: no fixed team found, fallback freq")
            result=await page.evaluate("() => { const vo=window.__vo; return vo? {idx:0, poolSize:vo.length, team:vo[0].name}:null; }")
            if not result: break
        idx=result["idx"]; pool_sz=result["poolSize"]
        log(f"  spin {spin+1}: {result['team']} idx={idx}/{pool_sz}")
        await page.evaluate(f"() => {{ const h=window.__h; h.idx={idx}; h.poolSz={pool_sz}; h.overrideReady=true; }}")
        spin_btn=page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first
        if not await spin_btn.is_visible(timeout=3000):
            log("  no SPIN"); break
        await spin_btn.click(timeout=5000)
        await asyncio.sleep(2.5)
        # track usage
        try:
            sel=await page.evaluate("() => { const r=window.__lastSpinResult; return r?{id:r.id,name:r.name}:null; }")
            if sel:
                await page.evaluate(f"() => {{ const h=window.__h; h.usage['{sel['id']}']=(h.usage['{sel['id']}']||0)+1; }}")
        except: pass
        cards=await page.evaluate("() => window.__readCards()")
        if not cards:
            log("    no cards"); continue
        # pick fixed player if available, else highest freq
        # Determine which fixed names are still needed and fit open slots
        needed=[n for _,n in FIXED_XI if n not in [p["name"] for p in picks]]
        # filter cards to those needed
        scored=[]
        for c in cards:
            if c.get("disabled"): continue
            name=c["name"]
            if name in needed:
                # priority by fixed order (earlier pos higher priority)
                prio = FIXED_NAMES.index(name)  # lower index = higher prio
                s = 10000 - prio*100 + c.get("b",0)+c.get("p",0)
                scored.append((s,c))
            else:
                # fallback: pick high freq/stat if fixed not available (should not happen)
                f=COMB.get(name,0)
                s = f*10 + c.get("b",0)
                scored.append((s,c))
        if not scored:
            log("    no enabled fixed cards"); continue
        scored.sort(key=lambda x: x[0], reverse=True)
        best=scored[0][1]
        log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) {'[FIXED]' if best['name'] in FIXED_SET else ''}")
        await page.locator("button").nth(best["btnIdx"]).click(timeout=3000)
        await asyncio.sleep(1.0)
        # position popup
        digits=await page.evaluate(r"""() => {
            const dlg=[...document.querySelectorAll('div')].find(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||'')&&d.querySelector('button'));
            const root=dlg||document; const out=[];
            for(const b of root.querySelectorAll('button')){
                const t=(b.textContent||'').trim();
                if(/^\d{1,2}$/.test(t)){
                    const st=b.getAttribute('style')||''; const om=st.match(/opacity:\s*([\d.]+)/);
                    out.push({n:parseInt(t), dis:!!b.disabled, op: om?parseFloat(om[1]):1});
                }
            }
            return out;
        }""")
        if digits:
            usable=[d["n"] for d in digits if not d["dis"] and d["op"]>0.85]
            if usable:
                # choose correct pos for this fixed player
                expected_pos=None
                for pos,name in FIXED_XI:
                    if name==best["name"]:
                        expected_pos=pos
                        break
                chosen=expected_pos if expected_pos in usable else usable[0]
                log(f"       pos {chosen} among {usable} (expected {expected_pos})")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{chosen}'&&!b.disabled){{b.click();return;}}
                }}""")
                await asyncio.sleep(0.5)
        picks.append({"name":best["name"],"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0)})
        await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{best['name'].replace(\"'\",\"\\\\'\")}'}}); if(h.openSlots.length) h.openSlots.shift(); }}")
        if len(picks)>=11:
            log("  All 11 fixed picked! " + ", ".join([p["name"] for p in picks]))
            break
    # verify fixed XI completeness
    missing=[n for _,n in FIXED_XI if n not in [p["name"] for p in picks]]
    if missing:
        log(f"  WARNING missing fixed: {missing}")
    else:
        log(f"  FIXED XI complete!")
    log("  Simulating...")
    sim=page.locator("button").filter(has_text=re.compile(r"SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000); await asyncio.sleep(2)
        skip=page.locator("button").filter(has_text=re.compile(r"SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000): await skip.click(timeout=3000)
        except: pass
        await asyncio.sleep(3)
    ss=SHOTS_DIR / f"fixed_d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)
    body=await page.inner_text("body")
    overs_m=re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val=float(overs_m.group(1)) if overs_m else None
    balls_val=int(round(overs_val*6)) if overs_val else None
    if balls_val and "HISTORY REWRITTEN" in body:
        if balls_val < best_balls[0]:
            best_balls[0]=balls_val
            best_overs[0]=overs_val
            log(f"  *** NEW BEST FASTEST: {balls_val} balls = {overs_val} overs ***")
        else:
            log(f"  win {balls_val} balls = {overs_val} overs (best {best_balls[0]})")
    if "HISTORY REWRITTEN" in body:
        log("  >>> WIN! HISTORY REWRITTEN <<<")
        claimed=False
        try:
            await page.wait_for_timeout(1500)
            for _ in range(20):
                claim=page.locator("button").filter(has_text=re.compile(r"CLAIM", re.I)).first
                if await claim.is_visible(timeout=800):
                    inp=page.locator("input[placeholder*='handle' i]").first
                    if not await inp.is_visible(timeout=400):
                        inp=page.locator("input").first
                    try:
                        if await inp.is_visible(timeout=600):
                            v=await inp.input_value()
                            if not v or len(v.strip())<2:
                                await inp.fill(HANDLE)
                                await page.wait_for_timeout(300)
                                log(f"  filled handle {HANDLE}")
                    except: pass
                    await claim.click(timeout=2000)
                    log("  clicked CLAIM →")
                    await page.wait_for_timeout(2500)
                    claimed=True
                    break
                if _%5==0:
                    try:
                        btns=await page.evaluate("() => [...document.querySelectorAll('button')].map(b=> (b.textContent||'').trim().slice(0,30)).filter(t=>t).join(' | ')")
                        log(f"  debug buttons {btns[:350]}")
                    except: pass
                await page.wait_for_timeout(400)
            if not claimed:
                log("  CLAIM not found, trying direct evaluate")
                try:
                    clicked=await page.evaluate("() => { for(const b of document.querySelectorAll('button')) if(/CLAIM/i.test(b.textContent||'')) { b.click(); return 1; } return 0; }")
                    log(f"  direct CLAIM clicked={clicked}")
                except: pass
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
            await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','k1387-{HANDLE}')")
        except Exception as e:
            log(f"  claim err {e}")
        log(f"  HOLDING {HOLD_SEC}s handle={HANDLE}...")
        await page.wait_for_timeout(HOLD_SEC*1000)
        try:
            ss2=SHOTS_DIR / f"fixed_d{num}_win_hold.png"
            await page.screenshot(path=str(ss2), full_page=True)
        except: pass
        again=page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
        try:
            if await again.is_visible(timeout=4000):
                await again.click(timeout=4000); await asyncio.sleep(2.5)
            else:
                await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(2000)
                await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
                easy=page.locator("button").filter(has_text=re.compile(r"^EASY", re.I)).first
                if await easy.is_visible(timeout=3000): await easy.click(timeout=3000); await asyncio.sleep(0.5)
                draft=page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
                if await draft.is_visible(timeout=3000): await draft.click(timeout=3000); await asyncio.sleep(2)
        except: pass
        return True
    for kw in ["CHOKED","HEARTBREAK","OUTCLASSED","UNPREPARED"]:
        if kw in body: log(f"  Result: {kw}"); break
    m=re.search(r"(\d+/\d+)\s", body)
    if m: log(f"  Score: {m.group(1)}")
    again=page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
    try:
        if await again.is_visible(timeout=3000): await again.click(timeout=3000); await asyncio.sleep(2)
    except: pass
    return False

async def main():
    log(f"spin_fixed11.py FIXED XI: {', '.join(FIXED_NAMES)} HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS}")
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx=await browser.new_context(viewport={"width":480,"height":1000}, device_scale_factor=2)
        page=await ctx.new_page()
        await setup_route_interception(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => {{ localStorage.setItem('five-hundred-handle','{HANDLE}'); localStorage.setItem('five-hundred-pid','k1387-{HANDLE}'); }}")
        log(f"Fixed PID k1387-{HANDLE}")
        ok_vo=await page.evaluate("() => !!window.__vo")
        log(f"Capture vo={'OK' if ok_vo else 'MISS'}")
        if not ok_vo: await browser.close(); return
        log(f"Teams: {await page.evaluate('() => window.__vo.length')}")
        seed=random.randint(1,2**31-1)
        js=INJECT_HACK_JS.replace("RAND_SEED", str(seed))
        await page.evaluate(js)
        log(f"Hack injected seed={seed}")
        easy=page.locator("button").filter(has_text=re.compile(r"^EASY", re.I)).first
        await easy.click(timeout=3000); await asyncio.sleep(0.5)
        draft=page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
        await draft.click(timeout=3000); await asyncio.sleep(2)
        log("Entered draft - infinite loop until stop")
        wins=0
        for i in range(1, MAX_DRAFTS+1):
            won=await one_draft(page,i)
            if won: wins+=1
            log(f"Progress: {wins}/{i} wins best {best_balls[0]} balls ({best_overs[0] if best_overs[0]!=999 else 'no win'} overs)")
        log(f"=== DONE {wins}/{MAX_DRAFTS} wins best {best_balls[0]} ===")
        await page.wait_for_timeout(3000)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
