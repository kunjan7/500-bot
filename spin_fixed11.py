"""
spin_fixed11.py - Fixed XI for 500-0.com (React rewrite, Sep 2026)
Forces: Rohit, Sachin, Virat, Viv, AB, Henri(Klaasen), Afridi, Wasim, Malcolm, Shane, Muthaia
Uses Math.random interception to control team spin + card picker for player selection.
Submits wins directly via leaderboard API (bypasses CLAIM button).
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
LB_URL = "https://500leaderboard.raasnhafiz.workers.dev"
SHOTS_DIR = Path(__file__).parent / "shots_fixed11"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "kumar6071")
MAX_DRAFTS = int(os.getenv("MAX_DRAFTS", "20"))
HOLD_SEC = int(os.getenv("HOLD_SEC", "10"))
SEED_DELAY = float(os.getenv("SEED_DELAY", "2"))

def _b36(n):
    if n <= 0:
        return "0"
    out = ""
    while n > 0:
        out = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + out
        n //= 36
    return out

def daily_pid():
    """Deterministic PID per UTC day so wins accumulate on ONE count-board id.
    Format matches game: base36(midnight_utc_ms) + 8-char suffix."""
    import datetime
    day = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    dt = datetime.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
    ts = int(dt.timestamp() * 1000)
    return _b36(ts) + "kumar607"

STABLE_PID = os.getenv("STABLE_PID", "").strip() or daily_pid()

FIXED_XI = [
    (1, "Rohit Sharma"), (2, "Sachin Tendulkar"), (3, "Virat Kohli"),
    (4, "Viv Richards"), (5, "AB de Villiers"), (6, "Heinrich Klaasen"),
    (7, "Shahid Afridi"), (8, "Wasim Akram"), (9, "Malcolm Marshall"),
    (10, "Shane Warne"), (11, "Muttiah Muralitharan"),
]
FIXED_NAMES = [n for _, n in FIXED_XI]
FIXED_SET = set(FIXED_NAMES)

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

best_balls = [999]

# Track picks per draft: list of {name, role, squadId}
current_picks = []

def gen_pid():
    """Generate PID in game format: base36 timestamp + random chars."""
    import time as _time
    ts = int(_time.time() * 1000)
    b36 = ""
    n = ts
    while n > 0:
        b36 = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + b36
        n //= 36
    rnd = "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(8))
    return b36 + rnd

async def api_seed(page, pid):
    """Register team with leaderboard via POST /seed, return sid or None."""
    xi_payload = [{"n": p["name"], "sq": p.get("squadId", "")} for p in current_picks]
    log(f"  SEED xi sample: {json.dumps(xi_payload[:3])}... ({len(xi_payload)} players)")
    for attempt in range(3):
        try:
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle, xi} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/seed', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle, xi: xi})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE, "xi": xi_payload})
            if result.get("ok"):
                sid = result.get("data", {}).get("sid", "")
                log(f"  SEED ok sid={sid[:20]}...")
                return sid
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SEED rate limited (429), waiting {wait}s (attempt {attempt+1}/3)...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SEED failed: {result}")
                return None
        except Exception as e:
            log(f"  SEED err: {e}")
            return None
    log("  SEED failed after 3 retries")
    return None

async def api_submit(page, pid, sid):
    """Submit win to leaderboard via POST /submit, return ranks or None."""
    for attempt in range(3):
        try:
            xi_payload = [{"n": p["name"], "r": p.get("role", "BAT"), "sq": p.get("squadId", "")} for p in current_picks]
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle, sid, xi} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/submit', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle, sid: sid, xi: xi})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE, "sid": sid, "xi": xi_payload})
            if result.get("ok"):
                ranks = result.get("data", {}).get("ranks", {})
                log(f"  SUBMIT ok! today={ranks.get('today','?')} most={ranks.get('most','?')}")
                return ranks
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SUBMIT rate limited (429), waiting {wait}s (attempt {attempt+1}/3)...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SUBMIT failed: {result}")
                return None
        except Exception as e:
            log(f"  SUBMIT err: {e}")
            return None
    log("  SUBMIT failed after 3 retries")
    return None

def map_role_from_card(card):
    """Map card role string to API role code."""
    r = card.get("role", "").upper()
    if r == "WK": return "WK"
    if r == "ALL-ROUNDER": return "AR"
    if r == "BOWLER": return "BWL"
    return "BAT"

async def get_squad_id(page, player_name):
    """Search __No for a player and return the first matching team's ID."""
    escaped = player_name.replace("'", "\\'")
    try:
        return await page.evaluate(f"""() => {{
            const No = window.__No;
            if (!No) return '';
            for (const t of No) {{
                if (t.players && t.players.some(p => p.n === '{escaped}')) return t.id;
            }}
            return '';
        }}""")
    except:
        return ''

async def api_seed_no_xi(page, pid):
    """Register with leaderboard via POST /seed without xi (fallback)."""
    for attempt in range(3):
        try:
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/seed', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE})
            if result.get("ok"):
                sid = result.get("data", {}).get("sid", "")
                log(f"  SEED (no xi) ok sid={sid[:20]}...")
                return sid
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SEED (no xi) rate limited (429), waiting {wait}s...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SEED (no xi) failed: {result}")
                return None
        except Exception as e:
            log(f"  SEED (no xi) err: {e}")
            return None
    return None

async def setup_route_interception(page):
    async def lb_log(route):
        req = route.request
        try:
            body = req.post_data or ""
        except:
            body = ""
        log(f"  [LB REQ] {req.method} {req.url[:150]} body={body[:300]}")
        resp = await route.fetch()
        try:
            txt = await resp.text()
            log(f"  [LB RESP] {resp.status} {txt[:500]}")
            await route.fulfill(response=resp, body=txt,
                content_type=resp.headers.get("content-type", "application/json"))
        except:
            await route.continue_()

    await page.route("**/*500leaderboard*submit*", lb_log)
    await page.route("**/*500leaderboard*board*", lb_log)
    await page.route("**/*raasnhafiz*workers.dev*submit*", lb_log)
    await page.route("**/*raasnhafiz*workers.dev*board*", lb_log)

    async def seed_cap(route):
        # Game auto-seeds (E1) at 10/11 picks with Ga()=STABLE_PID.
        # Capture its sid so our submit reuses the SAME session (no re-seed conflict).
        try:
            resp = await route.fetch()
            try:
                txt = await resp.text()
                try:
                    data = json.loads(txt)
                    sid = data.get("sid")
                    if sid:
                        try:
                            await page.evaluate(f"() => {{ (window.__seedSids = window.__seedSids || []).push('{sid}'); window.__lastSeedSid = '{sid}'; }}")
                        except:
                            pass
                        log(f"  [GAME SEED] sid={sid[:20]}...")
                except:
                    pass
                await route.fulfill(response=resp, body=txt,
                    content_type=resp.headers.get("content-type", "application/json"))
            except:
                await route.continue_()
        except:
            try:
                await route.continue_()
            except:
                pass

    await page.route("**/*500leaderboard*seed*", seed_cap)
    await page.route("**/*raasnhafiz*workers.dev*seed*", seed_cap)

    async def intercept(route):
        resp = await route.fetch()
        body = await resp.text()
        if "window.__No" not in body:
            body = body.replace(
                "],wt=(t,l,e)=>Math.max(l,Math.min(e,t));",
                "];window.__No=No;window.__o6=o6;window.__S6=S6;window.__A6=A6;wt=(t,l,e)=>Math.max(l,Math.min(e,t));")
            body = body.replace(
                "No[Math.floor(Math.random()*No.length)]",
                "(window.__gamePool=No,window.__lastSpinResult=No[Math.floor(Math.random()*No.length)])")
        await route.fulfill(response=resp, body=body, content_type="application/javascript")

    await page.route("**/*app*.js", intercept)

INJECT_HACK_JS = r"""
(() => {
    if (window.__hackReady) return;
    window.__hackReady = true;
    const _orig = Math.random;
    let _s = SEED;
    function _prng(){ _s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }
    window.__h = {on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}};
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
    window.__FIXED_XI = FIXED_JSON_PLACEHOLDER;
    window.__FIXED_SET = new Set(FIXED_JSON_PLACEHOLDER);
    window.__chooseTeamForNextFixed = function(){
        const No=window.__No, h=window.__h;
        if(!No||!h) return null;
        const picked=new Set(h.picked);
        const slots=[...h.openSlots];
        const lim=window.__o6||2;
        for(const name of window.__FIXED_XI){
            if(picked.has(name)) continue;
            let pool=No.filter(t=>{
                return t.players.some(p=>p.n===name && slots.some(s=>s>=p.r[0]&&s<=p.r[1]))
                    && (h.usage[t.id]||0)<lim;
            });
            if(pool.length){
                const idx=No.indexOf(pool[0]);
                return {idx, poolSize:pool.length, need:name, team:pool[0].name+" "+pool[0].season};
            }
        }
        return null;
    };
    window.__pickCard = function(cards){
        const picked=new Set(window.__h.picked);
        const needed=[];
        for(const name of window.__FIXED_XI){ if(!picked.has(name)) needed.push(name); }
        for(const n of needed){
            for(const c of cards){
                if(c.name===n && !c.disabled) return c;
            }
        }
        const enabled=cards.filter(c=>!c.disabled);
        if(!enabled.length) return null;
        enabled.sort((a,b)=>(b.b*2+b.p)-(a.b*2+a.p));
        return enabled[0];
    };
})();
"""
INJECT_HACK_JS = INJECT_HACK_JS.replace("SEED", "RAND_SEED")
INJECT_HACK_JS = INJECT_HACK_JS.replace("FIXED_JSON_PLACEHOLDER", json.dumps(FIXED_NAMES))

async def ensure_hack(page, seed=None):
    try:
        has = await page.evaluate("() => !!window.__h && !!window.__No && !!window.__chooseTeamForNextFixed")
    except:
        has = False
    if not has:
        for _ in range(10):
            try:
                if await page.evaluate("() => !!window.__No"): break
            except:
                pass
            await page.wait_for_timeout(500)
        s = seed or random.randint(1, 2**31 - 1)
        js = INJECT_HACK_JS.replace("RAND_SEED", str(s))
        try:
            await page.evaluate(js)
        except:
            pass
        log(f"  (injected hack seed={s})")
        await page.wait_for_timeout(700)

def read_cards_from_dom(dom_text):
    """Parse cards from React DOM text (innerText of buttons)"""
    cards = []
    lines = dom_text.split("\n")
    i = 0
    while i < len(lines):
        L = lines[i].strip()
        if L in ("BATTER", "BOWLER", "ALL-ROUNDER", "WK"):
            role = L
            name = None
            lo, hi, bb, pp, bl = 1, 11, 0, 0, 0
            j = i + 1
            while j < len(lines):
                L2 = lines[j].strip()
                rm = re.match(r'^(\d{1,2})[-\u2013](\d{1,2})$', L2)
                if rm:
                    lo, hi = int(rm.group(1)), int(rm.group(2))
                    j += 1
                    continue
                if L2 == "BAT" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        bb = int(prev)
                        j += 1
                        continue
                if L2 == "POW" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        pp = int(prev)
                        j += 1
                        continue
                if L2 == "BWL" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        bl = int(prev)
                        j += 1
                        continue
                if not L2.isdigit() and L2 not in ("BAT", "POW", "BWL") and not re.match(r'^\d{1,2}[-\u2013]\d{1,2}$', L2):
                    name = L2
                    j += 1
                    break
                j += 1
            if name and role:
                cards.append({"name": name, "role": role, "b": bb, "p": pp, "bl": bl, "lo": lo, "hi": hi})
            i = j
        else:
            i += 1
    return cards

async def get_cards_from_page(page):
    """Read card buttons from the React DOM"""
    try:
        result = await page.evaluate(r"""() => {
            const cards = [];
            const seen = new Set();
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = (b.innerText || '').trim();
                if (!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue;
                const st = b.getAttribute('style') || '';
                const om = st.match(/opacity:\s*([\d.]+)/);
                if (om && parseFloat(om[1]) < 0.85) continue;
                const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
                let name = null, role = '', lo = 1, hi = 11, bb = 0, pp = 0, bl = 0;
                for (let i = 0; i < lines.length; i++) {
                    const L = lines[i];
                    if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) { role = L.toUpperCase(); continue; }
                    const rm = L.match(/^(\d{1,2})[-\u2013](\d{1,2})$/);
                    if (rm) { lo = +rm[1]; hi = +rm[2]; continue; }
                    if (/^BAT$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { bb = +lines[i-1]; continue; }
                    if (/^POW$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { pp = +lines[i-1]; continue; }
                    if (/^BWL$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { bl = +lines[i-1]; continue; }
                }
                if (!name) {
                    for (const L of lines) {
                        if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) continue;
                        if (/^\d/.test(L)) continue;
                        if (/^(BAT|POW|BWL)$/i.test(L)) continue;
                        name = L; break;
                    }
                }
                if (!name || !role || seen.has(name)) continue;
                seen.add(name);
                const disabled = b.disabled || getComputedStyle(b).opacity < 0.5;
                let btnIdx = -1;
                const allBtns = document.querySelectorAll('button');
                for (let i = 0; i < allBtns.length; i++) {
                    if (allBtns[i].innerText && allBtns[i].innerText.includes(name)) {
                        btnIdx = i; break;
                    }
                }
                cards.push({name, role, disabled, b: bb, p: pp, bl, lo, hi, btnIdx});
            }
            return cards;
        }""")
        return result
    except Exception as e:
        log(f"  readCards err: {e}")
        return []

async def one_draft(page, num):
    log(f"=== DRAFT #{num} FIXED11 {HANDLE} ===")
    current_picks.clear()
    current_sid = None
    try:
        seed_n0 = await page.evaluate("() => (window.__seedSids||[]).length")
    except:
        seed_n0 = 0

    for _ in range(10):
        try:
            await page.wait_for_timeout(500)
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=800):
                break
        except:
            pass

    await ensure_hack(page)
    new_seed = random.randint(1, 2**31 - 1)
    try:
        await page.evaluate(f"() => window.__reseed({new_seed})")
    except:
        pass
    log(f"  seed={new_seed}")

    try:
        await page.evaluate("() => { const h=window.__h; h.picked=[]; h.openSlots=[1,2,3,4,5,6,7,8,9,10,11]; h.usage={}; }")
    except:
        await ensure_hack(page, seed=new_seed)

    picks = []
    needed_set = set(FIXED_NAMES)
    last_squad_id = ""

    for spin in range(15):
        team_result = await page.evaluate("() => window.__chooseTeamForNextFixed()")
        if not team_result:
            log(f"  spin {spin+1}: no team with needed player, picking random")
            team_result = await page.evaluate("() => { const No=window.__No,h=window.__h; if(!No)return null; const lim=window.__o6||2; const avail=No.filter(t=>(h.usage[t.id]||0)<lim); if(!avail.length)return null; const t=avail[Math.floor(Math.random()*avail.length)]; return {idx:No.indexOf(t),poolSize:avail.length,need:'*',team:t.name+' '+t.season}; }")
            if not team_result:
                log("  no teams available")
                break

        idx = team_result["idx"]
        pool_sz = team_result["poolSize"]
        need = team_result.get("need", "*")
        log(f"  spin {spin+1}: {team_result['team']} idx={idx}/{pool_sz} need={need}")

        await page.evaluate(f"() => {{ const h=window.__h; h.idx={idx}; h.poolSz={pool_sz}; h.overrideReady=true; }}")

        spin_btn = page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first
        if not await spin_btn.is_visible(timeout=3000):
            log("  no SPIN button")
            break
        await spin_btn.click(timeout=5000)
        await asyncio.sleep(2.5)

        try:
            sel = await page.evaluate("() => { const r=window.__lastSpinResult; return r?{id:r.id,name:r.name}:null; }")
            if sel:
                await page.evaluate(f"() => {{ const h=window.__h; h.usage['{sel['id']}']=(h.usage['{sel['id']}']||0)+1; }}")
                last_squad_id = sel["id"]
        except:
            pass

        await page.wait_for_timeout(1000)
        cards = await get_cards_from_page(page)
        if not cards:
            log("    no cards found, waiting more...")
            await page.wait_for_timeout(2000)
            cards = await get_cards_from_page(page)
        if not cards:
            log("    still no cards, skipping spin")
            continue

        card_names = [c["name"] for c in cards]
        log(f"    cards: {', '.join(card_names)}")

        picked_set = set(p["name"] for p in picks)
        best = None
        for n in FIXED_NAMES:
            if n not in picked_set:
                for c in cards:
                    if c["name"] == n and not c.get("disabled"):
                        best = c
                        break
                if best:
                    break

        if not best:
            enabled = [c for c in cards if not c.get("disabled")]
            if enabled:
                enabled.sort(key=lambda c: c.get("b", 0) * 2 + c.get("p", 0), reverse=True)
                best = enabled[0]
                log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) [FILLER]")
            else:
                log("    no enabled cards")
                continue
        else:
            log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) [FIXED]")

        btn_idx = best.get("btnIdx", -1)
        if btn_idx >= 0:
            await page.locator("button").nth(btn_idx).click(timeout=3000)
        else:
            await page.locator("button").filter(has_text=best["name"]).first.click(timeout=3000)
        await asyncio.sleep(1.0)

        digits = await page.evaluate(r"""() => {
            const dlgs = [...document.querySelectorAll('div')].filter(d =>
                d.className && String(d.className).includes('fixed') &&
                /Choose a batting position/i.test(d.textContent || '') &&
                d.querySelector('button'));
            const root = dlgs.length ? dlgs[dlgs.length-1] : document;
            const out = [];
            for (const b of root.querySelectorAll('button')) {
                const t = (b.textContent || '').trim();
                if (/^\d{1,2}$/.test(t)) {
                    const st = b.getAttribute('style') || '';
                    const om = st.match(/opacity:\s*([\d.]+)/);
                    out.push({n: parseInt(t), dis: !!b.disabled, op: om ? parseFloat(om[1]) : 1});
                }
            }
            return out;
        }""")

        if digits:
            usable = [d["n"] for d in digits if not d["dis"] and d["op"] > 0.85]
            if usable:
                expected_pos = None
                for pos, nm in FIXED_XI:
                    if nm == best["name"]:
                        expected_pos = pos
                        break
                chosen = expected_pos if expected_pos and expected_pos in usable else usable[0]
                log(f"       pos {chosen} among {usable}")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{chosen}'&&!b.disabled){{b.click();return;}}
                }}""")
                await asyncio.sleep(0.5)

        squad_id = await get_squad_id(page, best["name"])
        if not squad_id:
            squad_id = last_squad_id
        pick_entry = {"name": best["name"], "b": best.get("b", 0), "p": best.get("p", 0), "bl": best.get("bl", 0), "role": map_role_from_card(best), "squadId": squad_id}
        picks.append(pick_entry)
        current_picks.append(pick_entry)
        try:
            safe_name = best["name"].replace("'", "\\'")
            await page.evaluate(f"() => {{ const h=window.__h; h.picked.push('{safe_name}'); if(h.openSlots.length) h.openSlots.shift(); }}")
        except:
            pass

        if len(picks) >= 11:
            break

    fixed_count = sum(1 for p in picks if p["name"] in FIXED_SET)
    log(f"  Picked {len(picks)} players, {fixed_count}/11 fixed")
    missing = [n for _, n in FIXED_XI if n not in [p["name"] for p in picks]]
    if missing:
        log(f"  MISSING: {missing}")

    # Stable PID all day: never rotate per draft, else count-board fragments to v=1.
    # Game auto-seeds (E1) at 10/11 picks with Ga()=STABLE_PID — reuse ITS sid.
    # A manual re-seed with the same id conflicts server-side (one session per id),
    # which was causing sid=None -> submits skipped -> zero count-board wins.
    draft_pid = STABLE_PID
    await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{STABLE_PID}')")
    await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
    current_sid = None
    for _ in range(20):  # wait ~10s for game's seed response (fired at 10 picks)
        await page.wait_for_timeout(500)
        try:
            sids = await page.evaluate("() => (window.__seedSids||[])")
            if sids and len(sids) > seed_n0:
                current_sid = sids[-1]
                log(f"  GAME SEED sid={current_sid[:20]}...")
                break
        except:
            pass
    if not current_sid:
        try:
            last = await page.evaluate("() => window.__lastSeedSid || ''")
            if last:
                current_sid = last
                log(f"  GAME SEED (last) sid={current_sid[:20]}...")
        except:
            pass
    if not current_sid:
        log("  no game seed captured, manual seed fallback...")
        current_sid = await api_seed_no_xi(page, draft_pid)
        if not current_sid:
            log("  SEED (no xi) failed, trying with xi fallback...")
            current_sid = await api_seed(page, draft_pid)
    await asyncio.sleep(SEED_DELAY)

    log("  Simulating...")
    sim = page.locator("button").filter(has_text=re.compile(r"SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000)
        await asyncio.sleep(2)
        skip = page.locator("button").filter(has_text=re.compile(r"SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000):
                await skip.click(timeout=3000)
        except:
            pass
        await asyncio.sleep(3)

    ss = SHOTS_DIR / f"d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)

    body = await page.inner_text("body")
    overs_m = re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val = float(overs_m.group(1)) if overs_m else None
    balls_val = int(round(overs_val * 6)) if overs_val else None

    if "HISTORY REWRITTEN" in body:
        if balls_val and balls_val < best_balls[0]:
            best_balls[0] = balls_val
            log(f"  *** NEW BEST: {balls_val} balls = {overs_val} overs ***")
        else:
            log(f"  >>> WIN {balls_val} balls = {overs_val} overs <<<")

        await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{draft_pid}')")

        if current_sid:
            await asyncio.sleep(SEED_DELAY)
            ranks = await api_submit(page, draft_pid, current_sid)
            await asyncio.sleep(SEED_DELAY)
            if ranks:
                log(f"  SUBMIT returned: today #{ranks.get('today','?')} most #{ranks.get('most','?')}")

                log("  Polling leaderboard until entry is confirmed...")
                confirmed = False
                for poll in range(20):
                    await asyncio.sleep(5)
                    try:
                        lb_check = await page.evaluate(r"""async (params) => {
                            const {handle, pid} = params;
                            const out = {};
                            for (const w of ['today','most']) {
                                try {
                                    const r = await fetch('""" + LB_URL + r"""/board?window=' + w);
                                    if (r.ok) {
                                        const d = await r.json();
                                        const entries = d.top || [];
                                        const idx = entries.findIndex(e => e.handle === handle);
                                        if (idx >= 0) out[w] = {rank: idx+1, balls: entries[idx].balls, runs: entries[idx].runs};
                                        else out[w] = null;
                                    }
                                } catch(e) {}
                            }
                            try {
                                const r = await fetch('""" + LB_URL + r"""/count?window=today');
                                if (r.ok) {
                                    const d = await r.json();
                                    const entries = d.top || [];
                                    const idx = entries.findIndex(e => e.handle === handle);
                                    if (idx >= 0) out['count'] = {rank: idx+1, wins: entries[idx].v, id: entries[idx].id};
                                    else out['count'] = null;
                                }
                            } catch(e) {}
                            try {
                                const r = await fetch('""" + LB_URL + r"""/count?window=today&id=' + encodeURIComponent(pid));
                                if (r.ok) {
                                    const d = await r.json();
                                    if (d.you) out['you'] = d.you;
                                    else if (d.count) out['you'] = {v: d.count};
                                }
                            } catch(e) {}
                            return out;
                        }""", {"handle": HANDLE, "pid": STABLE_PID})
                        today_e = lb_check.get("today")
                        most_e = lb_check.get("most")
                        count_e = lb_check.get("count")
                        you_e = lb_check.get("you")
                        if today_e or count_e or you_e:
                            parts = []
                            if today_e: parts.append(f"fastest #{today_e['rank']} ({today_e['balls']} balls)")
                            if count_e: parts.append(f"most 500s #{count_e['rank']} ({count_e['wins']} wins)")
                            if you_e: parts.append(f"my id wins={you_e.get('v', you_e)}")
                            log(f"  CONFIRMED! {', '.join(parts)}")
                            confirmed = True
                            break
                        else:
                            log(f"  Poll {poll+1}/20: pending...")
                    except Exception as e:
                        log(f"  Poll {poll+1} err: {e}")
                if not confirmed:
                    log("  Leaderboard not confirmed after 100s, proceeding anyway")

                try:
                    ss_lb = SHOTS_DIR / f"d{num}_leaderboard.png"
                    await page.screenshot(path=str(ss_lb), full_page=True)
                    log(f"  Saved screenshot: {ss_lb.name}")
                except:
                    pass

                log(f"  Waiting {HOLD_SEC}s before next draft...")
                await page.wait_for_timeout(HOLD_SEC * 1000)
            else:
                log("  submit failed, retrying in 15s...")
                await page.wait_for_timeout(15000)
        else:
            log("  no sid, skipping submit")

    for kw in ["CHOKED", "HEARTBREAK", "OUTCLASSED", "UNPREPARED"]:
        if kw in body:
            log(f"  Result: {kw}")
            break
    if "HISTORY REWRITTEN" not in body:
        m = re.search(r"(\d+/\d+)\s", body)
        if m:
            log(f"  Score: {m.group(1)}")

    again = page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
    try:
        if await again.is_visible(timeout=3000):
            await again.click(timeout=3000)
            await asyncio.sleep(2)
        else:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
            await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{draft_pid}')")
            easy = page.locator("button").filter(has_text=re.compile(r"EASY", re.I)).first
            if await easy.is_visible(timeout=5000):
                await easy.click(timeout=5000, force=True)
                await asyncio.sleep(0.5)
            draft = page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
            if await draft.is_visible(timeout=5000):
                await draft.click(timeout=5000, force=True)
                await asyncio.sleep(2)
    except:
        pass
    return "HISTORY REWRITTEN" in body

async def main():
    log(f"spin_fixed11.py FIXED XI: {', '.join(FIXED_NAMES)}")
    log(f"HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} HOLD_SEC={HOLD_SEC} STABLE_PID={STABLE_PID}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx = await browser.new_context(viewport={"width": 480, "height": 1000}, device_scale_factor=2)
        page = await ctx.new_page()
        await setup_route_interception(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => {{ localStorage.setItem('five-hundred-handle','{HANDLE}'); localStorage.setItem('five-hundred-pid','{STABLE_PID}'); }}")
        log(f"Initial PID {STABLE_PID} (stable all day)")

        ok = await page.evaluate("() => !!window.__No")
        log(f"Capture No={'OK' if ok else 'MISS'}")
        if not ok:
            log("FAIL: could not capture teams")
            await browser.close()
            return
        team_count = await page.evaluate("() => window.__No.length")
        log(f"Teams: {team_count}")

        seed = random.randint(1, 2**31 - 1)
        js = INJECT_HACK_JS.replace("RAND_SEED", str(seed))
        await page.evaluate(js)
        log(f"Hack injected seed={seed}")

        easy = page.locator("button").filter(has_text=re.compile(r"EASY", re.I)).first
        if await easy.is_visible(timeout=5000):
            await easy.click(timeout=5000, force=True)
            await asyncio.sleep(0.5)
        draft = page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
        if await draft.is_visible(timeout=5000):
            await draft.click(timeout=5000, force=True)
            await asyncio.sleep(2)
        log("Entered draft - infinite loop")

        wins = 0
        for i in range(1, MAX_DRAFTS + 1):
            won = await one_draft(page, i)
            if won:
                wins += 1
            log(f"Progress: {wins}/{i} wins best {best_balls[0]} balls")

        log(f"=== DONE {wins}/{MAX_DRAFTS} wins best {best_balls[0]} ===")

        log("=== LEADERBOARD VERIFICATION ===")
        try:
            import urllib.request, urllib.parse
            for endpoint in [("board", "today"), ("board", "most"), ("count", "today")]:
                kind, window = endpoint
                url = f"{LB_URL}/{kind}?window={window}"
                req = urllib.request.Request(url)
                resp = urllib.request.urlopen(req, timeout=15)
                data = json.loads(resp.read())
                entries = data.get("top", [])
                found = [e for e in entries if e.get("handle") == HANDLE]
                if found:
                    e = found[0]
                    if kind == "count":
                        log(f"  {kind}/{window}: handle={e['handle']} wins={e.get('v',0)} id={e.get('id','')[:12]}")
                    else:
                        log(f"  {kind}/{window}: #{entries.index(e)+1} handle={e['handle']} balls={e['balls']} runs={e['runs']}")
                else:
                    log(f"  {kind}/{window}: NOT FOUND in top {len(entries)}")
            # Direct check of OUR stable id (count groups by id, not handle)
            url = f"{LB_URL}/count?window=today&id={urllib.parse.quote(STABLE_PID)}"
            req = urllib.request.Request(url)
            resp = urllib.request.urlopen(req, timeout=15)
            data = json.loads(resp.read())
            log(f"  count/today?id=STABLE_PID: you={data.get('you')} count={data.get('count')} top_n={len(data.get('top',[]))}")
        except Exception as e:
            log(f"  verification err: {e}")

        await page.wait_for_timeout(3000)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
