"""
spin_fastest.py — fastest-chase maximizer (<35 overs)
Targets backend win formula: batAvg>=86, powAvg>=89, attack>=90 -> win, balls = 282 - B*72 +-6 where B=N/16.5
N = (bat-86)+(pow-89)+(attack-90). Need N>=16.5 for B=1 -> avg 210, min 204.
Team+card picker maximizes b/p/bl stats, not freq. Keeps exploration for lucky low rolls.
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
SHOTS_DIR = Path(__file__).parent / "shots_hack"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "kunjan1387c")  # distinct cloud handle to avoid local collision
MAX_DRAFTS = int(os.getenv("MAX_DRAFTS", "1000"))
HOLD_AFTER_WIN_SEC = int(os.getenv("HOLD_SEC", "20"))
TARGET_BALLS = int(os.getenv("TARGET_BALLS", "209"))  # <210 = <35 overs
STOP_ON_TARGET = os.getenv("STOP_ON_TARGET", "0") == "1"

FREQ_PATH = Path(__file__).parent / "freq_map.json"
with open(FREQ_PATH, encoding="utf-8") as f:
    _FM = json.load(f)
FREQ_UNDER40 = _FM["freq_under40"]
COMBINED_FREQ = {}
for k,v in _FM["freq_top100"].items():
    COMBINED_FREQ[k]=v
for k,v in FREQ_UNDER40.items():
    COMBINED_FREQ[k]=max(v*2, COMBINED_FREQ.get(k,0))
FREQ_JSON = json.dumps(COMBINED_FREQ)
POS_JSON = json.dumps(_FM["pos_freq"])
TOP12 = set(list(FREQ_UNDER40.keys())[:15])

def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)

async def setup_route_interception(page):
    async def intercept(route):
        resp = await route.fetch()
        body = await resp.text()
        if "window.__f6" not in body:
            body = body.replace("analysis:Z}}var Mc=", "analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc=")
            body = body.replace("];function c6(){", "];window.__vo=vo;window.__K2=K2;function c6(){")
            body = body.replace("Mt[Math.floor(Math.random()*Mt.length)]",
                "(window.__gamePool=Mt,window.__lastSpinResult=Mt[Math.floor(Math.random()*Mt.length)])")
        await route.fulfill(response=resp, body=body, content_type="application/javascript")
    await page.route("**/*app*.js", intercept)

INJECT_HACK_JS = r"""
(() => {
    if (window.__hackReady) return;
    window.__hackReady = true;
    const _orig = Math.random;
    let _s = SEED;
    function _prng(){ _s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }
    window.__h = { on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}, rerollTeam:null, explore:false };
    window.__reseed = (s) => { _s = s|0; };
    window.__setExplore = (v) => { window.__h.explore = !!v; };
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
    window.__FREQ = FREQ_JSON_PLACEHOLDER;
    window.__POS_FREQ = POS_JSON_PLACEHOLDER;
    // ---- FASTEST team picker: maximize b/p/bl for N ----
    window.__chooseTeamFast = function(){
        const vo=window.__vo, h=window.__h;
        if(!vo||!h) return null;
        const picked=new Set(h.picked.map(p=>p.name));
        const slots=[...h.openSlots];
        const K2=window.__K2||2;
        const pool=vo.filter(t=>{
            if(!t.players.some(p=>!picked.has(p.n) && slots.some(s=>s>=p.r[0]&&s<=p.r[1]))) return false;
            if((h.usage[t.id]||0)>=K2) return false;
            if(h.rerollTeam && t.id===h.rerollTeam) return false;
            return true;
        });
        if(!pool.length) return null;
        function teamScore(team){
            // stat-maximizing: sum of b*1.0 + p*1.2 + bl*1.0 for available players fitting open slots
            // plus huge bonus for 90+ stats (thresholds for win)
            let s=0;
            let bestB=0, bestP=0, bestBL=0;
            let cnt=0;
            for(const p of team.players){
                if(picked.has(p.n)) continue;
                if(!slots.some(sl=>sl>=p.r[0]&&sl<=p.r[1])) continue;
                cnt++;
                let contrib = p.b*1.0 + p.p*1.2 + p.bl*0.8;
                if(p.b>=90) contrib+=15;
                if(p.p>=90) contrib+=15;
                if(p.bl>=90) contrib+=12;
                if(p.b>=86 && p.p>=89) contrib+=10; // win threshold combo
                s += contrib;
                if(p.b>bestB) bestB=p.b;
                if(p.p>bestP) bestP=p.p;
                if(p.bl>bestBL) bestBL=p.bl;
            }
            // bonus for team containing single best batter/powder
            s += bestB*0.5 + bestP*0.5;
            // if no high-stat players, fall back to freq to still get usable team
            if(s<50){
                for(const p of team.players){
                    if(picked.has(p.n)) continue;
                    const f=(window.__FREQ[p.n]||0);
                    s += f*0.5;
                }
            }
            return s;
        }
        const ranked = pool.map((t,i)=>({t,i,s:teamScore(t)})).sort((a,b)=>b.s-a.s);
        let choice = ranked[0];
        if(window.__h.explore && ranked.length>1 && _prng() < 0.30){
            const r=_prng();
            if(r<0.6 && ranked.length>1) choice=ranked[1];
            else if(ranked.length>2) choice=ranked[2];
        }
        let bi=choice.i, bs=choice.s, bn=choice.t.name+" "+choice.t.season;
        return {idx:bi, poolSize:pool.length, team:bn, score:bs};
    };
    window.__chooseTeamFreq = window.__chooseTeamFast; // override for compatibility
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

INJECT_HACK_JS = INJECT_HACK_JS.replace("SEED", "RAND_SEED").replace("FREQ_JSON_PLACEHOLDER", FREQ_JSON).replace("POS_JSON_PLACEHOLDER", POS_JSON)

best_overs = [999]
best_balls = [999]

async def ensure_hack(page, seed=None):
    try:
        has = await page.evaluate("() => !!window.__h && !!window.__vo && !!window.__chooseTeamFast")
    except:
        has=False
    if not has:
        for _ in range(10):
            try:
                ok = await page.evaluate("() => !!window.__vo")
                if ok: break
            except: pass
            await page.wait_for_timeout(500)
        s = seed or random.randint(1, 2**31-1)
        js = INJECT_HACK_JS.replace("RAND_SEED", str(s))
        try: await page.evaluate(js)
        except: pass
        log(f"  (re-injected hack seed={s})")
        await page.wait_for_timeout(700)

async def one_draft(page, num):
    log(f"=== DRAFT #{num} handle={HANDLE} target<{TARGET_BALLS+1} balls ===")
    for _ in range(8):
        try:
            await page.wait_for_timeout(500)
            has_spin = await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=800)
            if has_spin:
                break
        except: pass
    await ensure_hack(page)
    new_seed = random.randint(1, 2**31-1)
    try: await page.evaluate(f"() => window.__reseed({new_seed})")
    except: pass
    try: await page.evaluate("() => window.__setExplore(true)")
    except: pass
    log(f"  seed={new_seed}")
    for attempt in range(4):
        try:
            await page.evaluate("() => { const h=window.__h; h.picked=[]; h.openSlots=[1,2,3,4,5,6,7,8,9,10,11]; h.usage={}; h.rerollTeam=null; }")
            break
        except Exception as e:
            log(f"  retry hack init attempt {attempt+1}: {e}")
            await ensure_hack(page, seed=new_seed)
            await page.wait_for_timeout(800)
    picks=[]
    for spin in range(15):
        result = await page.evaluate("() => window.__chooseTeamFast()")
        if not result:
            log(f"  spin {spin+1}: empty pool")
            break
        idx=result["idx"]; pool_sz=result["poolSize"]
        log(f"  spin {spin+1}: {result['team']} (statScore={result['score']:.1f}, idx={idx}/{pool_sz})")
        await page.evaluate(f"() => {{ const h=window.__h; h.idx={idx}; h.poolSz={pool_sz}; h.overrideReady=true; }}")
        spin_btn = page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first
        if not await spin_btn.is_visible(timeout=3000):
            log("  no SPIN button"); break
        await spin_btn.click(timeout=5000)
        await asyncio.sleep(2.5)
        try:
            sel = await page.evaluate("() => { const r=window.__lastSpinResult; return r?{id:r.id,name:r.name,season:r.season}:null; }")
        except: sel=None
        if sel:
            tid=sel["id"]
            try:
                await page.evaluate(f"() => {{ const h=window.__h; h.usage['{tid}']=(h.usage['{tid}']||0)+1; }}")
                usage=await page.evaluate(f"() => window.__h.usage['{tid}']")
                log(f"    tracked: {sel['name']} {sel['season']} (usage={usage})")
            except: pass
        cards = await page.evaluate("() => window.__readCards()")
        if not cards:
            log("    no cards found"); continue
        # FASTEST card picker: maximize b*1.0 + p*1.4 + bl*0.6, with BAT>=90 POW>=90 bonus
        scored=[]
        for c in cards:
            if c.get("disabled"): continue
            b=c.get("b",0); p=c.get("p",0); bl=c.get("bl",0)
            s = b*1.0 + p*1.4 + bl*0.5
            if b>=90: s+=20
            if p>=90: s+=25
            if b>=86 and p>=89: s+=15
            if bl>=90: s+=10
            # tiny freq tie-break to keep win-rate high
            f=COMBINED_FREQ.get(c["name"],0)
            s += f*0.05
            scored.append((s,c))
        if not scored:
            log(f"    no enabled cards from {len(cards)} total"); continue
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        bestScore=scored[0][0]
        log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) statScore={bestScore:.1f}")
        if len(scored)>1:
            alts=", ".join([f"{c['name']}({b}/{p})" for _,c in scored[:3] for b in [c.get('b',0)] for p in [c.get('p',0)]])
            # already have best, just log
            pass
        btns = page.locator("button")
        await btns.nth(best["btnIdx"]).click(timeout=3000)
        await asyncio.sleep(1.0)
        digits = await page.evaluate(r"""() => {
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
                best_pos = usable[0]
                # for fastest, prefer earliest position that fits role to keep top order strongest
                # but also try to place high BAT early
                if best.get('b',0)>=90 and 1 in usable:
                    best_pos=1
                elif best.get('b',0)>=88 and 2 in usable:
                    best_pos=2
                log(f"       pos: choosing {best_pos} among {usable}")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{best_pos}'&&!b.disabled){{b.click();return;}}
                }}""")
                await asyncio.sleep(0.5)
        picks.append({"name":best["name"],"role":best["role"],"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0)})
        safe = best["name"].replace("'","\\'")
        await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{safe}'}}); if(h.openSlots.length) h.openSlots.shift(); }}")
        if len(picks)>=11:
            log("  All 11 picked!"); break
    # compute predicted N for logging
    if len(picks)>=11:
        top7=picks[:7]
        last4=picks[7:11]
        bat=sum(p['b'] for p in top7)/7
        powv=sum(p['p'] for p in top7)/7
        att=sum(p['bl'] for p in last4)/4
        N=max(0, bat-86 + (powv-89) + (att-90))
        B=min(1, N/16.5)
        expBalls=282 - B*72
        log(f"  Predicted: bat={bat:.1f} pow={powv:.1f} att={att:.1f} N={N:.1f} B={B:.2f} expBalls={expBalls:.0f}±6 (target<{TARGET_BALLS+1})")
        # also log picks
        for p in picks:
            log(f"    - {p['name']:<22} BAT{p['b']}/POW{p['p']}/BWL{p['bl']}")
    log("  Simulating...")
    sim = page.locator("button").filter(has_text=re.compile(r"SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000); await asyncio.sleep(2)
        skip = page.locator("button").filter(has_text=re.compile(r"SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000): await skip.click(timeout=3000)
        except: pass
        await asyncio.sleep(3)
    ss = SHOTS_DIR / f"fast_d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)
    body = await page.inner_text("body")
    overs_m = re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val = float(overs_m.group(1)) if overs_m else None
    balls_m = None
    if overs_val:
        balls_m = int(round(overs_val*6))
    else:
        # fallback parse balls from history
        m2=re.search(r"(\d+)\s*balls", body, re.I)
        if m2: balls_m=int(m2.group(1))
    if balls_m and "HISTORY REWRITTEN" in body:
        if balls_m < best_balls[0]:
            best_balls[0]=balls_m
            best_overs[0]=overs_val if overs_val else balls_m/6
            log(f"  *** NEW BEST FASTEST: {balls_m} balls = {overs_val} overs (prev best {best_balls[0]}) ***")
        else:
            log(f"  win balls {balls_m} = {overs_val} overs (best {best_balls[0]} balls)")
        if balls_m <= TARGET_BALLS:
            log(f"  >>> TARGET ACHIEVED <{TARGET_BALLS+1} balls ({TARGET_BALLS/6:.1f} overs)! <<<")
            # still claim and hold
    if "HISTORY REWRITTEN" in body:
        log("  >>> WIN! HISTORY REWRITTEN <<< balls=%s overs=%s" % (balls_m, overs_val))
        try:
            for _ in range(12):
                claim = page.locator("button").filter(has_text=re.compile(r"CLAIM MY SPOT", re.I)).first
                if await claim.is_visible(timeout=800):
                    inp = page.locator("input[placeholder='pick a handle']").first
                    try:
                        if await inp.is_visible(timeout=600):
                            v = await inp.input_value()
                            if not v or len(v.strip())<2:
                                await inp.fill(HANDLE)
                                await page.wait_for_timeout(300)
                                log(f"  filled handle {HANDLE}")
                    except: pass
                    await claim.click(timeout=2000)
                    log("  clicked CLAIM MY SPOT →")
                    await page.wait_for_timeout(2500)
                    body2 = await page.inner_text("body")
                    if "ALL-TIME" in body2 or "500 CLUB" in body2:
                        log("  post done")
                    break
                await page.wait_for_timeout(500)
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        except Exception as e:
            log(f"  auto-claim err: {e}")
        log(f"  HOLDING win screen {HOLD_AFTER_WIN_SEC}s for handle={HANDLE}...")
        try:
            await page.wait_for_timeout(HOLD_AFTER_WIN_SEC*1000)
        except:
            await asyncio.sleep(HOLD_AFTER_WIN_SEC)
        try:
            ss2 = SHOTS_DIR / f"fast_d{num}_win_hold.png"
            await page.screenshot(path=str(ss2), full_page=True)
            log(f"  hold screenshot: {ss2}")
        except: pass
        if balls_m and balls_m <= TARGET_BALLS and STOP_ON_TARGET:
            log(f"  STOP_ON_TARGET set, exiting after target win")
            return True  # signal to stop outer loop
        again = page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
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
    again = page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
    try:
        if await again.is_visible(timeout=3000): await again.click(timeout=3000); await asyncio.sleep(2)
    except: pass
    return False

async def main():
    log(f"spin_fastest.py — HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} TARGET={TARGET_BALLS} balls ({TARGET_BALLS/6:.1f} overs) STOP_ON_TARGET={STOP_ON_TARGET}")
    log(f"Cloud vs local handle: cloud={HANDLE}, local should keep kunjan1387")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx = await browser.new_context(viewport={"width":480,"height":1000}, device_scale_factor=2)
        page = await ctx.new_page()
        await setup_route_interception(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        ok_vo=await page.evaluate("() => !!window.__vo")
        ok_f6=await page.evaluate("() => !!window.__f6")
        log(f"Capture: vo={'OK' if ok_vo else 'MISS'} f6={'OK' if ok_f6 else 'MISS'}")
        if not ok_vo: log("FATAL"); await browser.close(); return
        log(f"Teams: {await page.evaluate('() => window.__vo.length')}")
        seed=random.randint(1,2**31-1)
        js=INJECT_HACK_JS.replace("RAND_SEED", str(seed))
        await page.evaluate(js)
        log(f"Hack injected (seed={seed})")
        easy=page.locator("button").filter(has_text=re.compile(r"^EASY", re.I)).first
        await easy.click(timeout=3000); await asyncio.sleep(0.5)
        draft=page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
        await draft.click(timeout=3000); await asyncio.sleep(2)
        log("Entered draft")
        wins=0
        for i in range(1, MAX_DRAFTS+1):
            won=await one_draft(page,i)
            if won: wins+=1
            # check target balls achievement
            if best_balls[0] <= TARGET_BALLS and STOP_ON_TARGET:
                log(f"=== TARGET <{TARGET_BALLS} balls ACHIEVED after {i} drafts, best={best_balls[0]} balls ===")
                break
        log(f"=== DONE: {wins}/{MAX_DRAFTS} wins, best={best_balls[0]} balls ({best_overs[0] if best_overs[0]!=999 else 'no win'} overs) ===")
        if best_balls[0] <= TARGET_BALLS:
            log(f"*** SUCCESS <35 overs: {best_balls[0]} balls = {best_balls[0]/6:.1f} overs ***")
        await page.wait_for_timeout(3000)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
