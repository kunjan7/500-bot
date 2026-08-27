"""
500-0.com SPIN INTERCEPTOR BOT - FINAL VERSION
================================================
REVERSE-ENGINEERING FINDINGS:
  - 38 squads in `vo` array, selected via Math.random()
  - Win condition: avg_bat(1-7)>=86, avg_pow(1-7)>=89, avg_bwl(8-11)>=90, wk present, >=3 bwl>=70
  - Speed formula: balls = 282 - clamp(N/16.5, 0,1)*72  where N=(bat-86)+(pow-89)+(bwl-90)
  - WK flag is wk:1 in squad data
  - Math.random() is fully client-side → we override it via Playwright add_init_script
  - No server validation of which squad was shown!

STRATEGY:
  We inject a Math.random() override BEFORE page load.
  On each spin, we force the squad index to one of our top-10 elite squads.
  We then greedily pick the best available player for each slot.

RUN:  python spin_intercept_v2.py
STOP: Ctrl+C
"""
import asyncio, json, re, sys, pathlib, time
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE     = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_intercept.json"
SHOT_DIR = BASE / "screenshots_intercept"; SHOT_DIR.mkdir(exist_ok=True)

# ── ALL 38 SQUAD IDs IN ORDER (matches vo array in app.js) ───────────────────
ALL_SQUADS = [
    "pakistan1990s","pakistan2000s","pakistan2010s","pakistan2020s",
    "india1990s","india2000s","india2010s","india2020s",
    "australia1990s","australia2000s","australia2010s","australia2020s",
    "england1990s","england2000s","england2010s","england2020s",
    "southafrica1990s","southafrica2000s","southafrica2010s","southafrica2020s",
    "newzealand1990s","newzealand2000s","newzealand2010s","newzealand2020s",
    "westindies1980s","westindies1990s","westindies2010s","westindies2020s",
    "srilanka1990s","srilanka2000s","srilanka2010s","srilanka2020s",
    "afghanistan2020s","bangladesh2010s","ireland2010s","netherlands2020s",
    "kenya2000s","zimbabwe1990s",
]

# ── TOP SQUADS by combined player quality (from analysis) ─────────────────────
TARGET_SQUADS = [
    # Slots 1-3: High POW batters
    "india2020s",        # Rohit Sharma(94p), Virat(88p)
    "australia2020s",    # Travis Head(94p), David Warner(90p)
    "westindies1980s",   # Viv Richards(96p/96b) ← also has best bowlers
    # Slots 4-7: WK + middle order power
    "england2010s",      # Jos Buttler(WK,96p), Jonny Bairstow(WK), Jason Roy(92p)
    "australia2000s",    # Adam Gilchrist(WK,93p), Ponting(89p), Andrew Symonds(90p)
    "india2000s",        # Sachin(95b), Sehwag(94p), MS Dhoni(WK,88p)
    # Slots 8-11: Elite bowlers
    "westindies1980s",   # Malcolm Marshall(96bl), Joel Garner(94bl), Michael Holding(93bl)
    "srilanka1990s",     # Muttiah Muralitharan(96bl), Chaminda Vaas(88bl)
    "australia1990s",    # Shane Warne(95bl), Glenn McGrath(93bl)
    "pakistan1990s",     # Wasim Akram(95bl), Waqar Younis(93bl), Saqlain(92bl)
]

# ── KNOWN PLAYER DATABASE (from vo_squads.js) ─────────────────────────────────
# Format: name -> {b, p, bl, wk, lo, hi, squad}
# This lets us pick intelligently even before reading the page DOM
KNOWN_PLAYERS = {}

def load_known_players():
    """Parse all player data from the saved squad JS."""
    squad_file = BASE / "vo_squads.js"
    if not squad_file.exists():
        return
    js = squad_file.read_text(encoding='utf-8', errors='replace')
    squad_blocks = re.split(r'(?=\{id:")', js)
    for block in squad_blocks:
        sid_m = re.search(r'id:"([^"]+)"', block)
        if not sid_m: continue
        sid = sid_m.group(1)
        pats = re.findall(
            r'\{n:"([^"]+)",r:\[(\d+),(\d+)\],b:(\d+),p:(\d+),bl:(\d+)(,wk:1)?(,ar:1)?\}',
            block
        )
        for pt in pats:
            name = pt[0]
            if name not in KNOWN_PLAYERS:
                KNOWN_PLAYERS[name] = {
                    'name': name, 'lo': int(pt[1]), 'hi': int(pt[2]),
                    'b': int(pt[3]), 'p': int(pt[4]), 'bl': int(pt[5]),
                    'wk': bool(pt[6]), 'squad': sid
                }

load_known_players()
print(f"Loaded {len(KNOWN_PLAYERS)} unique players from squad data")

# ── MATH.RANDOM INTERCEPT SCRIPT ──────────────────────────────────────────────
def make_intercept_js(target_squads):
    """
    JavaScript injected before page load to override Math.random().
    Forces specific squads on each spin call.
    
    HOW THE GAME USES Math.random():
      Squad selection: vo[Math.floor(Math.random() * vo.length)]
      Animation reel:  vo[Math.floor(Math.random() * vo.length)]  (×14 more times)
      Simulation:      many calls for ball-by-ball outcomes
    
    We override to return a value that maps to our desired squad index.
    """
    indices = []
    for sid in target_squads:
        if sid in ALL_SQUADS:
            indices.append(ALL_SQUADS.index(sid))
    n = len(ALL_SQUADS)

    return f"""
(function() {{
    var TARGETS = {json.dumps(indices)};
    var N_SQUADS = {n};
    var origRandom = Math.random.bind(Math);

    // Spin state tracking
    window.__interceptEnabled = true;
    window.__nextSpinTarget = -1;  // -1 = auto-pick from TARGETS
    window.__spinsFired = 0;
    window.__callsThisSpin = 0;

    // Our Python script sets this before calling SPIN
    window.__armNextSpin = function(targetIdx) {{
        window.__nextSpinTarget = targetIdx >= 0 ? targetIdx : -1;
        window.__callsThisSpin = 0;
        window.__interceptEnabled = true;
    }};

    Math.random = function() {{
        if (!window.__interceptEnabled) return origRandom();

        window.__callsThisSpin++;

        // The FIRST Math.random() call after arming = squad selection call
        if (window.__callsThisSpin === 1 && window.__nextSpinTarget !== -2) {{
            var idx;
            if (window.__nextSpinTarget >= 0) {{
                idx = window.__nextSpinTarget;
            }} else {{
                // Auto-cycle through targets
                idx = TARGETS[window.__spinsFired % TARGETS.length];
            }}
            window.__spinsFired++;
            window.__nextSpinTarget = -2;  // consumed - don't fire again until re-armed

            var val = (idx + 0.5) / N_SQUADS;
            console.log('[INTERCEPT] spin#' + window.__spinsFired + ' -> squad idx ' + idx + ' val=' + val.toFixed(4));
            return val;
        }}

        return origRandom();
    }};

    console.log('[INTERCEPT] Ready. Targeting squads: {json.dumps([ALL_SQUADS[i] for i in indices[:5]])}...');
}})();
"""

# ── DOM HELPERS ───────────────────────────────────────────────────────────────
READ_SQUAD_JS = """() => {
    const out = [];
    for (const btn of document.querySelectorAll('button')) {
        const nameEl = btn.querySelector('.text-sm.font-medium');
        if (!nameEl) continue;
        const name = (nameEl.textContent || '').trim();
        if (!name) continue;
        const spans = [...btn.querySelectorAll('span')];
        let role = '', rng = null;
        for (const s of spans) {
            const t = (s.textContent || '').trim();
            const m = t.match(/^(\\d+)\\s*[\\u2013\\u2014-]\\s*(\\d+)$/);
            if (m && !rng) rng = [parseInt(m[1]), parseInt(m[2])];
            else if (/^(BATTER|BOWLER|ALL-ROUNDER|WK|WICKET-KEEPER)$/i.test(t)) role = t.toUpperCase();
        }
        const ratings = {};
        for (const d of btn.querySelectorAll('div.text-right')) {
            const lab = d.querySelector('div:last-child');
            const val = d.querySelector('div.disp');
            if (lab && val) {
                const L = (lab.textContent||'').trim();
                const V = parseInt((val.textContent||'').trim());
                if (!isNaN(V)) ratings[L] = V;
            }
        }
        const style = btn.getAttribute('style') || '';
        const om = style.match(/opacity:\\s*([\\d.]+)/);
        const opacity = om ? parseFloat(om[1]) : 1;
        out.push({
            name, role,
            lo: rng ? rng[0] : 1, hi: rng ? rng[1] : 11,
            b: ratings.BAT ?? 0, p: ratings.POW ?? 0, bl: ratings.BWL ?? 0,
            enabled: !btn.disabled && opacity > 0.85
        });
    }
    return out;
}"""

async def body_text(page):
    try: return await page.evaluate("() => document.body.innerText")
    except: return ""

async def click_btn(page, txt, exact=False):
    try:
        return await page.evaluate("""([txt, exact]) => {
            const want = txt.toUpperCase();
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim().toUpperCase();
                if ((exact ? t === want : t.includes(want)) && !b.disabled) { b.click(); return true; }
            }
            return false;
        }""", [txt, exact])
    except: return False

async def click_player(page, name):
    return await page.evaluate("""(name) => {
        for (const btn of document.querySelectorAll('button')) {
            const el = btn.querySelector('.text-sm.font-medium');
            if (el && (el.textContent||'').trim() === name) {
                const style = btn.getAttribute('style')||'';
                const m = style.match(/opacity:\\s*([\\d.]+)/);
                const op = m ? parseFloat(m[1]) : 1;
                if (!btn.disabled && op > 0.85) { btn.click(); return true; }
            }
        }
        return false;
    }""", name)

NAME_RE = re.compile(r"^[A-Z][A-Z .''`\u2019\-]+$")
SKIP_WORDS = {"WK","BAT","BWL","AR","THE DRAFT","ALL ROUNDER","WICKETKEEPER","FILL"}

async def draft_truth(page):
    txt = await body_text(page)
    seg = txt.split("Fill all 11 positions.", 1)
    seg = seg[1] if len(seg) > 1 else txt
    for stop in ("RE-ROLL","SPIN","SIMULATE","START"):
        seg = seg.split(stop, 1)[0]
    lines = [l.strip() for l in seg.splitlines()]
    pos_map = {}
    for i in range(len(lines) - 1):
        if re.fullmatch(r"(10|11|[1-9])", lines[i]) and NAME_RE.fullmatch(lines[i+1]) and lines[i+1] not in SKIP_WORDS:
            pos_map[int(lines[i])] = lines[i+1]
    m = re.search(r"(\d{1,2})\s*/\s*11", txt)
    cnt = int(m.group(1)) if m else len(pos_map)
    return cnt, pos_map

async def choose_position(page, prefer_order):
    chosen = None
    for _ in range(24):
        btns = await page.evaluate("""() => {
            const out = [];
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim();
                if (!/^(10|11|[1-9])$/.test(t)) continue;
                const n = parseInt(t);
                const style = b.getAttribute('style')||'';
                const m = style.match(/opacity:\\s*([\\d.]+)/);
                out.push({n, dis: !!b.disabled, op: m ? parseFloat(m[1]) : 1});
            }
            return out;
        }""")
        usable = [x for x in btns if not x['dis'] and x['op'] > 0.85]
        if usable:
            if len(usable) == 1:
                n = usable[0]['n']
                await page.evaluate("(n) => { for(const b of document.querySelectorAll('button')) if((b.innerText||'').trim()===String(n)&&!b.disabled){b.click();return;} }", n)
                chosen = n; break
            for pref in prefer_order:
                if any(x['n'] == pref for x in usable):
                    await page.evaluate("""(n) => {
                        for (const b of document.querySelectorAll('button')) {
                            const t = (b.innerText||'').trim();
                            if (t === String(n)) {
                                const s = b.getAttribute('style')||'';
                                const m = s.match(/opacity:\\s*([\\d.]+)/);
                                if (!b.disabled && (m?parseFloat(m[1]):1) > 0.85) { b.click(); return; }
                            }
                        }
                    }""", pref)
                    chosen = pref; break
            if chosen: break
            n = usable[0]['n']
            await page.evaluate("(n) => { for(const b of document.querySelectorAll('button')) if((b.innerText||'').trim()===String(n)&&!b.disabled){b.click();return;} }", n)
            chosen = n; break
        await asyncio.sleep(0.25)
    return chosen

# ── PLAYER SELECTION LOGIC ────────────────────────────────────────────────────
def best_for_slot(squad, slot, taken, assigned):
    """Pick best available player for the given slot."""
    free_slots = [q for q in range(1,12) if q not in assigned]
    is_bwl_slot = slot >= 8
    has_wk = any(KNOWN_PLAYERS.get(assigned[q].get('name',''), {}).get('wk') or
                 (assigned[q].get('role','').upper() in ('WK','WICKET-KEEPER'))
                 for q in assigned)

    candidates = []
    for c in squad:
        if c['name'] in taken or not c.get('enabled'): continue
        # Must be able to fill this slot
        if not (c['lo'] <= slot <= c['hi']): continue

        # Use known data to augment DOM data if DOM ratings missing
        known = KNOWN_PLAYERS.get(c['name'], {})
        b = c['b'] if c['b'] > 0 else known.get('b', 50)
        p = c['p'] if c['p'] > 0 else known.get('p', 50)
        bl = c['bl'] if c['bl'] > 0 else known.get('bl', 50)
        wk = known.get('wk', False) or 'WK' in c.get('role','').upper()
        c['_b'], c['_p'], c['_bl'], c['_wk'] = b, p, bl, wk

        if is_bwl_slot:
            score = bl * 0.85 + p * 0.10 + b * 0.05
        else:
            score = p * 0.55 + b * 0.35
            if wk and not has_wk: score += 8  # big bonus for first WK
            if wk and has_wk: score -= 3       # penalty for duplicate WK

        candidates.append((score, c))

    if not candidates: return None
    candidates.sort(reverse=True)
    return candidates[0][1]

# ── WIN/RESULT DETECTION ──────────────────────────────────────────────────────
WIN_KW  = ("500 CLUB","YOU DID IT","CHASED","PERFECT CHASE","HISTORY","CONGRATULATIONS")
FAIL_KW = ("FELL SHORT","HEARTBREAK","ALL OUT","SO CLOSE","DENIED","COLLAPSED","LOST")

async def wait_result(page, sid, baseline_txt, timeout=120):
    t0 = time.time()
    base_lines = {l.strip() for l in baseline_txt.splitlines()}
    while time.time() - t0 < timeout:
        cur = await body_text(page)
        novel = "\n".join(l for l in cur.splitlines() if l.strip() and l.strip() not in base_lines)
        up = novel.upper()
        if "FAST" in up:   await click_btn(page, "FAST", exact=True)
        if "SKIP" in up:   await click_btn(page, "SKIP TO END"); await asyncio.sleep(3)
        m  = re.search(r"\b(\d{3,4})\s*/\s*(\d)\b", novel)
        ov = re.search(r"(\d{1,3}\.\d)\s*OVER", up)
        ctx = any(k in up for k in ("OVER","BALL","WICKET","SHORT","FELL","CHASED"))
        win  = (any(k in up for k in WIN_KW) and ctx) or "500 CLUB" in up
        fail = any(k in up for k in FAIL_KW) or (m and ctx and int(m.group(1)) < 500)
        if win or fail:
            try: await page.screenshot(path=str(SHOT_DIR/f"s{sid}_result.png"), full_page=True)
            except: pass
            sc = int(m.group(1)) if m else (500 if win else None)
            return {"score": sc, "wkts": int(m.group(2)) if m else None,
                    "overs": ov.group(1) if ov else None,
                    "win": bool(win or (sc and sc >= 500)),
                    "timeout": False, "snippet": novel[:300]}
        await asyncio.sleep(0.8)
    try: await page.screenshot(path=str(SHOT_DIR/f"s{sid}_timeout.png"), full_page=True)
    except: pass
    return {"score": None, "win": False, "timeout": True}

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding='utf-8'))
        except: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding='utf-8')

# ── MAIN DRAFT SESSION ────────────────────────────────────────────────────────
async def draft_session(pw, sid):
    rec = {"session": sid, "ts": datetime.now().isoformat(), "drafted": [], "success": False}

    browser = await pw.chromium.launch(headless=False)
    ctx = await browser.new_context(viewport={"width": 480, "height": 1000})

    # INJECT Math.random override BEFORE page load
    await ctx.add_init_script(script=make_intercept_js(TARGET_SQUADS))
    page = await ctx.new_page()

    try:
        log("  Loading 500-0.com with Math.random() intercepted...")
        await page.goto("https://500-0.com", wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(2.5)

        # Verify interception worked
        spin_count = await page.evaluate("() => typeof window.__armNextSpin")
        log(f"  Intercept status: __armNextSpin={spin_count}")

        # Navigate to draft
        await click_btn(page, "EASY");  await asyncio.sleep(0.4)
        await click_btn(page, "DRAFT"); await asyncio.sleep(2.0)

        assigned, taken = {}, set()
        stall = 0

        for slot in range(1, 12):
            is_bwl = slot >= 8
            log(f"\n  ── Slot {slot}/11 ({'BWL' if is_bwl else 'BAT/WK'}) ──")

            # ARM the interceptor - forces our target squad on next spin
            await page.evaluate("() => window.__armNextSpin(-1)")  # auto-cycle

            # Click SPIN
            ok = await click_btn(page, "SPIN", exact=True)
            if not ok:
                await asyncio.sleep(1.5)
                ok = await click_btn(page, "SPIN", exact=True)

            # Wait for animation + squad display
            await asyncio.sleep(4.0)

            # Read squad from page
            squad = await page.evaluate(READ_SQUAD_JS)
            squad_fired = await page.evaluate("() => window.__spinsFired")
            log(f"  Spins fired: {squad_fired} | Players visible: {len(squad)}")

            if len(squad) < 4:
                # Squad didn't load properly - spin again
                log("  Squad not visible, waiting more...")
                await asyncio.sleep(3)
                squad = await page.evaluate(READ_SQUAD_JS)

            # Augment with known data
            for c in squad:
                known = KNOWN_PLAYERS.get(c['name'], {})
                if c['b'] == 0: c['b'] = known.get('b', 50)
                if c['p'] == 0: c['p'] = known.get('p', 50)
                if c['bl'] == 0: c['bl'] = known.get('bl', 50)

            visible_names = [c['name'] for c in squad if c.get('enabled', True)][:5]
            log(f"  Squad: {visible_names}")

            # Pick best player for this slot
            player = best_for_slot(squad, slot, taken, assigned)
            if not player:
                log(f"  No valid player for slot {slot} — trying any available")
                avail = [c for c in squad if c['name'] not in taken and c.get('enabled')]
                if avail:
                    player = avail[0]
                else:
                    log("  Completely empty squad! Retrying spin...")
                    stall += 1
                    if stall > 3: return None
                    continue

            log(f"  Pick: {player['name']} [b={player.get('_b', player['b'])} p={player.get('_p', player['p'])} bl={player.get('_bl', player['bl'])} wk={player.get('_wk', False)}]")

            # Click the player
            clicked = await click_player(page, player['name'])
            if not clicked:
                log(f"  Click failed - trying visible players")
                for c in squad:
                    if c['name'] not in taken and c.get('enabled'):
                        if await click_player(page, c['name']):
                            player = c; clicked = True; break

            if not clicked:
                log("  All clicks failed"); stall += 1
                if stall > 3: return None
                continue

            await asyncio.sleep(0.4)
            # Handle position popup
            free = [q for q in range(1,12) if q not in assigned]
            prefer = [slot] + [x for x in free if x != slot]
            pos = await choose_position(page, prefer)
            log(f"    Position popup: chose={pos}")

            # Verify registration
            registered = False
            for _ in range(15):
                await asyncio.sleep(0.5)
                cnt, pos_map = await draft_truth(page)
                if player['name'].upper() in pos_map.values():
                    registered = True; break

            if registered:
                real_q = next(q for q,nm in pos_map.items() if nm == player['name'].upper())
                is_wk = KNOWN_PLAYERS.get(player['name'], {}).get('wk', False)
                assigned[real_q] = {**player, 'wk': is_wk}
                taken.add(player['name'])
                rec["drafted"].append({"pos": real_q, "name": player['name'],
                                       "b": player.get('_b', player['b']),
                                       "p": player.get('_p', player['p']),
                                       "bl": player.get('_bl', player['bl']),
                                       "wk": is_wk})
                log(f"  ✓ {player['name']} → pos {real_q}")
                stall = 0
            else:
                log(f"  ✗ {player['name']} did NOT register"); stall += 1
                if stall > 3: return None

        # ── Compute expected performance ──────────────────────────────────────
        cnt, _ = await draft_truth(page)
        log(f"\n  Draft: {cnt}/11 players")

        bat7 = [assigned[q] for q in sorted(assigned) if q <= 7]
        bwl4 = [assigned[q] for q in sorted(assigned) if q >= 8]
        abat = sum(p.get('_b',p['b']) for p in bat7) / max(1,len(bat7))
        apow = sum(p.get('_p',p['p']) for p in bat7) / max(1,len(bat7))
        abwl = sum(p.get('_bl',p['bl']) for p in bwl4) / max(1,len(bwl4))
        has_wk = any(p.get('wk') for p in assigned.values())
        n70    = sum(1 for p in assigned.values() if p.get('_bl',p.get('bl',0)) >= 70)

        # Speed formula from f6
        N = max(0, (abat-86) + (apow-89) + (abwl-90))
        B = min(1.0, N / 16.5)
        exp_balls = round(282 - B*72)
        exp_overs = round(exp_balls/6, 1)

        win_ok = has_wk and n70 >= 3 and abat >= 86 and apow >= 89 and abwl >= 90
        log(f"\n  BAT={abat:.1f} POW={apow:.1f} BWL={abwl:.1f} WK={has_wk} n70={n70}")
        log(f"  Win condition: {'✅ YES' if win_ok else '❌ NO'}")
        log(f"  Speed: N={N:.2f} B={B:.3f} → ~{exp_balls} balls ({exp_overs} overs)")

        rec["metrics"] = {"avg_bat":round(abat,2),"avg_pow":round(apow,2),"avg_bwl":round(abwl,2),
                          "has_wk":has_wk,"n70":n70,"exp_balls":exp_balls,"exp_overs":exp_overs,"win_ok":win_ok}

        if not win_ok:
            log("  Team doesn't meet win threshold — aborting to retry")
            return None

        # ── Simulate ──────────────────────────────────────────────────────────
        baseline = await body_text(page)
        await asyncio.sleep(1.0)
        try: await page.screenshot(path=str(SHOT_DIR/f"s{sid}_presim.png"), full_page=True)
        except: pass

        sim_clicked = False
        for label in ("SIMULATE","START","PLAY MATCH"):
            if await click_btn(page, label, exact=True):
                sim_clicked = True; break
        if not sim_clicked:
            sim_clicked = await click_btn(page, "SPIN", exact=True)
        log(f"  Simulation started: {sim_clicked}")
        if not sim_clicked: return None

        res = await wait_result(page, sid, baseline)
        rec.update(res)
        rec["success"] = bool(res.get("win"))

        if res.get("win"):
            log(f"\n  🏆 500 CLUB! Score={res['score']} | {res.get('overs','?')} overs (expected {exp_overs})")
        else:
            log(f"\n  ❌ Score={res.get('score')} timeout={res.get('timeout')}")

    except Exception as e:
        import traceback; traceback.print_exc()
        rec["error"] = str(e)
    finally:
        try: await browser.close()
        except: pass

    return rec

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
async def main():
    total = wins = 0
    log("=" * 70)
    log("  500-0.com SPIN INTERCEPTOR v2 - Math.random() override active")
    log("  Target: fastest 500 chase using elite squad forcing")
    log(f"  Top squads: {', '.join(TARGET_SQUADS[:5])}...")
    log("=" * 70)

    async with async_playwright() as pw:
        while True:
            try:
                total += 1
                log(f"\n{'='*70}\n  RUN #{total} | Wins: {wins}\n{'='*70}")

                rec = None
                for attempt in range(3):
                    r = await draft_session(pw, total)
                    if r is not None:
                        rec = r; break
                    log(f"  Attempt {attempt+1} returned None — retrying")
                    await asyncio.sleep(1)

                if rec:
                    save_run(rec)
                    if rec.get("success"):
                        wins += 1
                        log(f"\n🏆🏆🏆 WIN #{wins}! Score={rec.get('score')} Overs={rec.get('overs')} 🏆🏆🏆")
                    else:
                        log(f"  Total: {wins} wins / {total} runs")

                await asyncio.sleep(2)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"OUTER ERROR: {e}")
                import traceback; traceback.print_exc()
                await asyncio.sleep(3)

    log(f"\nFINAL: {wins} wins in {total} runs")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped")
