"""
spin_freq.py — freq-maximizing drafter.
Uses extracted Overall Player Frequency (Under 40 overs) to force spins toward teams
containing the highest-frequency players, and always picks the highest-frequency
available card in that team.

Mechanism: same proven spin interception as spin_hack.py (route injection + Math.random patch).
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
SHOTS_DIR = Path(__file__).parent / "shots_hack"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "kunjan1387")
MAX_DRAFTS = int(os.getenv("MAX_DRAFTS", "1000"))
STOP_ON_WIN = os.getenv("STOP_ON_WIN", "0") == "1"
HOLD_AFTER_WIN_SEC = int(os.getenv("HOLD_SEC", "20"))
EXPLORE_VARIATION = os.getenv("EXPLORE", "1") == "1"  # try other combos for lowest overs

FREQ_PATH = Path(__file__).parent / "freq_map.json"
with open(FREQ_PATH, encoding="utf-8") as f:
    _FM = json.load(f)
FREQ_UNDER40 = _FM["freq_under40"]  # name -> occurrences (under 40 overs)
FREQ_TOP100 = _FM["freq_top100"]
POS_FREQ = _FM["pos_freq"]  # P1..P11 -> [(name, freq), ...]

# Combined freq for injection — under40 is primary (fastest teams), fallback to top100
COMBINED_FREQ = {}
for k,v in FREQ_TOP100.items():
    COMBINED_FREQ[k]=v
for k,v in FREQ_UNDER40.items():
    COMBINED_FREQ[k]=max(v*2, COMBINED_FREQ.get(k,0))  # weight under40 2x

FREQ_JSON = json.dumps(COMBINED_FREQ)
POS_JSON = json.dumps(POS_FREQ)

# Top N high-freq set for logging
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
    // ---- FREQ data injected from Python ----
    window.__FREQ = FREQ_JSON_PLACEHOLDER;
    window.__POS_FREQ = POS_JSON_PLACEHOLDER;

    // ---- FREQ-maximizing team picker ----
    window.__chooseTeamFreq = function(){
        const vo=window.__vo, h=window.__h, FREQ=window.__FREQ;
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
        // score: sum of FREQ of *available* players that fit an open slot
        // + small position-bonus if player is top-freq for that slot range
        function teamScore(team){
            let s=0;
            let bestSingle=0;
            for(const p of team.players){
                if(picked.has(p.n)) continue;
                if(!slots.some(sl=>sl>=p.r[0]&&sl<=p.r[1])) continue;
                const f=FREQ[p.n]||0;
                // big weight: each avail high-freq player contributes f*10
                const contrib = f*10;
                s += contrib;
                if(f>bestSingle) bestSingle=f;
                // stat fallback to break ties among zero-freq teams
                if(f===0){
                    if(p.b>=90) s+=3; else if(p.b>=86) s+=2;
                    if(p.p>=90) s+=2;
                    if(p.bl>=90) s+=3;
                }
            }
            // boost team that contains the single highest-freq available player overall
            s += bestSingle*2;
            return s;
        }
        // rank by freqScore, then optionally explore other combos (for lowest overs hunting)
        const ranked = pool.map((t,i)=>({t,i,s:teamScore(t)})).sort((a,b)=>b.s-a.s);
        let choice = ranked[0];
        // 35% chance to pick 2nd/3rd best to try other high-freq combinations while still high-freq
        if(window.__h.explore && ranked.length>1 && _prng() < 0.35){
            const r=_prng();
            if(r<0.6 && ranked.length>1) choice=ranked[1];
            else if(ranked.length>2) choice=ranked[2];
        }
        let bi=choice.i, bs=choice.s, bn=choice.t.name+" "+choice.t.season;
        // fallback: if all scores 0 (no freq), pick stat-best
        if(bs<=0){
            let bestStat=-1;
            pool.forEach((t,i)=>{
                let s=0; for(const p of t.players){ if(picked.has(p.n)) continue; s+=p.b+p.p+p.bl; }
                if(s>bestStat){bestStat=s; bi=i; bn=t.name+" "+t.season; bs=s;}
            });
        }
        return {idx:bi, poolSize:pool.length, team:bn, score:bs};
    };

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

# inject real JSON
INJECT_HACK_JS = INJECT_HACK_JS.replace("SEED", "RAND_SEED").replace("FREQ_JSON_PLACEHOLDER", FREQ_JSON).replace("POS_JSON_PLACEHOLDER", POS_JSON)

best_overs = [999]  # global best
async def ensure_hack(page, seed=None):
    try:
        has = await page.evaluate("() => !!window.__h && !!window.__vo && !!window.__chooseTeamFreq")
    except:
        has=False
    if not has:
        # wait for vo to appear (route injection needs page load)
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
    log(f"=== DRAFT #{num} ===")
    # ensure draft screen is ready (SPIN button or DRAFT AGAIN handling)
    for _ in range(8):
        try:
            # if we are still on win screen, wait for DRAFT AGAIN to be clickable from previous win handler
            await page.wait_for_timeout(500)
            has_spin = await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=800)
            if has_spin:
                break
        except: pass
    await ensure_hack(page)
    # reseed PRNG each draft for variation (keeps exploring new combos)
    new_seed = random.randint(1, 2**31-1)
    try: await page.evaluate(f"() => window.__reseed({new_seed})")
    except: pass
    try: await page.evaluate(f"() => window.__setExplore({str(EXPLORE_VARIATION).lower()})")
    except: pass
    log(f"  seed={new_seed} explore={EXPLORE_VARIATION}")
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
        result = await page.evaluate("() => window.__chooseTeamFreq()")
        if not result:
            log(f"  spin {spin+1}: empty pool")
            break
        idx=result["idx"]; pool_sz=result["poolSize"]
        log(f"  spin {spin+1}: {result['team']} (freqScore={result['score']}, idx={idx}/{pool_sz})")
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

        # FREQ-maximizing card picker: FREQ dominates, stats break ties
        scored=[]
        for c in cards:
            if c.get("disabled"): continue
            f = COMBINED_FREQ.get(c["name"], 0)
            # massive freq bonus: ensures highest-freq card in this team is picked
            s = f*1000 + c.get("b",0) + c.get("p",0) + c.get("bl",0)
            # tiny bonus if card's freq aligns with an open slot's pos-freq leader
            scored.append((s,f,c))

        if not scored:
            log(f"    no enabled cards from {len(cards)} total"); continue
        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][2]; bestF=scored[0][1]
        log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) freq={bestF} {'[HIGH-FREQ]' if best['name'] in TOP12 else ''}")
        # also log top 3 candidates for debug
        if len(scored)>1:
            alts=", ".join([f"{c['name']}({f})" for _,f,c in scored[:3]])
            log(f"       candidates: {alts}")

        btns = page.locator("button")
        await btns.nth(best["btnIdx"]).click(timeout=3000)
        await asyncio.sleep(1.0)

        # position popup — pick best slot per TYPPP/pos-freq if possible
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
                # prefer position where this player's name is frequent (POS_FREQ)
                best_pos = usable[0]
                # find if player is in POS_FREQ for any usable slot
                freq_pos_bonus={}
                for slot in usable:
                    key=f"P{slot}"
                    lst=POS_FREQ.get(key,[])
                    # lst is list of (name, freq)
                    for nm, fr in lst:
                        if nm==best["name"]:
                            freq_pos_bonus[slot]=fr
                if freq_pos_bonus:
                    best_pos=max(freq_pos_bonus, key=lambda k: freq_pos_bonus[k])
                    log(f"       pos: choosing {best_pos} (freq-best) among {usable}")
                else:
                    log(f"       pos: choosing {best_pos} among {usable}")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{best_pos}'&&!b.disabled){{b.click();return;}}
                }}""")
                await asyncio.sleep(0.5)

        picks.append({"name":best["name"],"role":best["role"],"b":best.get("b",0),"p":best.get("p",0),"bl":best.get("bl",0),"freq":bestF})
        safe = best["name"].replace("'","\\'")
        await page.evaluate(f"() => {{ const h=window.__h; h.picked.push({{name:'{safe}'}}); if(h.openSlots.length) h.openSlots.shift(); }}")
        if len(picks)>=11:
            log("  All 11 picked!"); break

    # summary
    high_cnt=sum(1 for p in picks if p["name"] in COMBINED_FREQ and COMBINED_FREQ[p["name"]]>=40)
    top12_cnt=sum(1 for p in picks if p["name"] in TOP12)
    log(f"  Draft summary: {len(picks)} picks, {top12_cnt}/11 from TOP15-under40, {high_cnt}/11 freq>=40, picks: {[p['name'] for p in picks]}")
    # show freq breakdown
    for p in picks:
        log(f"    - {p['name']:<22} freq={COMBINED_FREQ.get(p['name'],0):>3} BAT{p['b']}/POW{p['p']}/BWL{p['bl']}")

    log("  Simulating...")
    sim = page.locator("button").filter(has_text=re.compile(r"SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000); await asyncio.sleep(2)
        skip = page.locator("button").filter(has_text=re.compile(r"SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000): await skip.click(timeout=3000)
        except: pass
        await asyncio.sleep(3)
    ss = SHOTS_DIR / f"freq_d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)
    body = await page.inner_text("body")
    # parse overs for lowest-overs tracking (e.g. "36.2" overs)
    overs_m = re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val = float(overs_m.group(1)) if overs_m else None
    if overs_val and "HISTORY REWRITTEN" in body:
        if overs_val < best_overs[0]:
            best_overs[0]=overs_val
            log(f"  *** NEW BEST OVERS: {overs_val} (prev best {best_overs[0]}) ***")
        else:
            log(f"  overs {overs_val} (best so far {best_overs[0]})")

    if "HISTORY REWRITTEN" in body:
        log("  >>> WIN! HISTORY REWRITTEN <<<")
        # --- auto-claim leaderboard (robust) ---
        claimed=False
        try:
            # wait a bit for modal animation
            await page.wait_for_timeout(1500)
            for _ in range(20):
                # broader CLAIM search (handles arrow/emoji changes) + also check div[role=button]
                claim = page.locator("button").filter(has_text=re.compile(r"CLAIM", re.I)).first
                if await claim.is_visible(timeout=800):
                    inp = page.locator("input[placeholder*='handle' i]").first
                    if not await inp.is_visible(timeout=400):
                        inp = page.locator("input").first
                    try:
                        if await inp.is_visible(timeout=600):
                            v = await inp.input_value()
                            if not v or len(v.strip())<2:
                                await inp.fill(HANDLE)
                                await page.wait_for_timeout(300)
                                log(f"  filled handle {HANDLE}")
                            else:
                                log(f"  handle already '{v}'")
                    except Exception as ie:
                        log(f"  handle fill err {ie}")
                    try:
                        await claim.click(timeout=2000)
                        log("  clicked CLAIM →")
                    except Exception as ce:
                        log(f"  click err {ce}")
                        try:
                            await page.evaluate("() => { for(const b of document.querySelectorAll('button')) if(/CLAIM/i.test(b.textContent||'')) { b.click(); return true; } }")
                            log("  fallback evaluate click CLAIM")
                        except: pass
                    await page.wait_for_timeout(2500)
                    body2 = await page.inner_text("body")
                    if "ALL-TIME" in body2 or "500 CLUB" in body2 or "RANK" in body2:
                        log("  post attempt done, checking rank...")
                    claimed=True
                    break
                # debug: log available buttons when not found
                if _==5 or _==10 or _==15:
                    try:
                        btns = await page.evaluate("() => [...document.querySelectorAll('button')].map(b=> (b.textContent||'').trim().slice(0,40)).filter(t=>t).join(' | ')")
                        log(f"  debug buttons try {_}: {btns[:400]}")
                        has_input = await page.evaluate("() => !!document.querySelector('input')")
                        log(f"  debug has_input={has_input}")
                    except: pass
                await page.wait_for_timeout(400)
            if not claimed:
                log("  CLAIM button not found after 20 tries, trying direct evaluate + localStorage + fetch POST")
                try:
                    await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
                    clicked = await page.evaluate("() => { for(const b of document.querySelectorAll('button')) if(/CLAIM/i.test(b.textContent||'')) { b.click(); return 1; } for(const b of document.querySelectorAll('[role=button]')) if(/CLAIM/i.test(b.textContent||'')) { b.click(); return 1; } return 0; }")
                    log(f"  direct evaluate CLAIM clicked={clicked}")
                    # fallback: try direct API POST via fetch (if UI fails, post via JS fetch to leaderboard)
                    try:
                        post_res = await page.evaluate(f"""async () => {{
                            try {{
                                const pid = localStorage.getItem('five-hundred-pid') || 'k1387-{HANDLE}';
                                const r = await fetch('https://500leaderboard.raasnhafiz.workers.dev/board', {{method:'GET'}});
                                return 'board GET ok '+r.status;
                            }} catch(e) {{ return 'fetch err '+e; }}
                        }}""")
                        log(f"  fallback fetch test: {post_res[:200] if isinstance(post_res, str) else str(post_res)[:200]}")
                    except Exception as fe:
                        log(f"  fetch test err {fe}")
                    await page.wait_for_timeout(2000)
                except Exception as e:
                    log(f"  direct click err {e}")
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
            await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','k1387-{HANDLE}')")
        except Exception as e:
            log(f"  auto-claim err: {e}")
        if not claimed:
            log("  WARNING: win not claimed via UI, will still count if localStorage handle set - checking board after hold")
        log(f"  HOLDING win screen {HOLD_AFTER_WIN_SEC}s for manual view (handle={HANDLE})...")
        try:
            await page.wait_for_timeout(HOLD_AFTER_WIN_SEC*1000)
        except:
            await asyncio.sleep(HOLD_AFTER_WIN_SEC)
        try:
            ss2 = SHOTS_DIR / f"freq_d{num}_win_hold.png"
            await page.screenshot(path=str(ss2), full_page=True)
            log(f"  hold screenshot: {ss2}")
        except: pass
        # always continue for lowest-overs hunting (unless STOP_ON_WIN=1)
        if STOP_ON_WIN:
            return True
        again = page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
        try:
            if await again.is_visible(timeout=4000):
                await again.click(timeout=4000); await asyncio.sleep(2.5)
            else:
                # fallback: reload draft page
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
    log(f"spin_freq.py — HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} STOP_ON_WIN={STOP_ON_WIN}")
    log(f"Freq map: {len(COMBINED_FREQ)} players, TOP15: {list(FREQ_UNDER40.keys())[:10]}")
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
            if won: wins+=1; 
            if won and STOP_ON_WIN: break
        log(f"=== DONE: {wins}/{MAX_DRAFTS} wins ===")
        await page.wait_for_timeout(3000)
        await browser.close()

if __name__=="__main__":
    asyncio.run(main())
