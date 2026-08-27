"""
500-0.com COMPLETE REVERSE ENGINEERING + SPIN INTERCEPTION BOT
==============================================================

KEY FINDINGS FROM JS ANALYSIS:
================================

1. SPIN MECHANISM (client-side, 100% controllable):
   - vo = array of 38 squads (Pakistan1990s, India2000s, etc.)
   - Each spin: picks a RANDOM squad from vo using Math.random()
   - Bot intercepts Math.random() to FORCE desired squad
   - No server verification of which squad was shown!

2. SEEDED RNG (a6 function):
   function a6(seed) {
     return function() {
       seed |= 0; seed = seed + 1831565813 | 0;
       let n = Math.imul(seed ^ seed>>>15, 1|seed);
       return (n = n + Math.imul(n ^ n>>>7, 61|n) ^ n, ((n ^ n>>>14)>>>0) / 4294967296);
     }
   }
   - The simulation uses this seeded RNG when a seed is provided
   - We can predict EXACT simulation results for any seed!

3. WIN CONDITION (n6 function) - THE EXACT FORMULA:
   Requires ALL of these:
   a) has WK role player
   b) >=3 players with BWL >= 70
   c) avg BAT (slots 1-7) >= 86
   d) avg POW (slots 1-7) >= 89
   e) avg BWL (slots 8-11) >= 90
   Then: 70% chance of exactly 500, 30% chance of 496-499

4. OVERS/SPEED (f6 function) - HOW FAST:
   If WIN tier:
   N = max(0, avg_bat - 86 + avg_pow - 89 + avg_attack - 90)
   B = clamp(N/16.5, 0, 1)           ← normalized score bonus
   balls = round(clamp(282 - B*72 + rand(-6,6), 204, 300))
   
   So:
   - MINIMUM possible balls = 204 (34 overs) when B=1 (max bonus)
   - MAXIMUM possible balls = 300 (50 overs) when B=0 (minimum bonus)
   - TARGET for <38 overs (228 balls): need B > (282-228)/72 = 0.75
   - B=0.75 requires N >= 0.75 * 16.5 = 12.375
   - N = (avg_bat - 86) + (avg_pow - 89) + (avg_attack - 90)
   
   avg_attack = avg BWL of slots 8-11
   
   FOR <38 OVERS: need avg_bat + avg_pow + avg_attack >= 86+89+90 + 12.4
   = avg_bat >= 90 (if others are at threshold)
   OR avg_pow >= 93 (key lever - most impactful)
   OR avg_attack >= 94 (elite bowlers)

5. BEST SQUAD COMBINATIONS (from vo data):
   westindies1980s: Viv Richards(b=96,p=96), Clive Lloyd, Gordon Greenidge
   england2010s: Jos Buttler(b=84,p=96 WK), Ben Stokes, Jonny Bairstow
   southafrica2010s: AB de Villiers(b=95,p=98 WK), Heinrich Klaasen
   
6. INTERFERENCE STRATEGY:
   Override window.Math.random in the browser context so that:
   - When the game picks a squad (1 of 38): return value that selects desired squad
   - When animation runs (15 frames): allow random
   - When simulation runs: allow or fix seed

IMPLEMENTATION: Playwright + page.add_init_script to inject Math.random override
"""

import asyncio, json, re, sys, pathlib, time
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BASE     = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_intercept.json"
SHOT_DIR = BASE / "screenshots_intercept"; SHOT_DIR.mkdir(exist_ok=True)

# ── ALL 38 SQUAD IDs (from vo array) ─────────────────────────────────────────
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

# ── TARGET SQUADS (highest BAT+POW players) ───────────────────────────────────
# From leaderboard analysis: these squads have the best players for fast chasing
TARGET_SQUADS = [
    "westindies1980s",    # Viv Richards(96p), Gordon Greenidge, Clive Lloyd, Malcolm Marshall(96bwl)
    "southafrica2010s",   # AB de Villiers(98p WK), Klaasen(95p WK)
    "england2010s",       # Buttler(96p WK), Bairstow(90p WK), Stokes, Archer
    "india2010s",         # Virat Kohli(94p), Rohit Sharma(94p), MS Dhoni(WK)
    "westindies2010s",    # Chris Gayle(94p), Kieron Pollard, Jason Holder
    "southafrica2000s",   # AB de Villiers, Graeme Smith, Lance Klusener(93p)
    "pakistan2000s",      # Wasim Akram, Waqar Younis(93bwl), Shahid Afridi(91p)
    "australia2000s",     # Adam Gilchrist(93p WK), Ricky Ponting, Matthew Hayden
    "srilanka1990s",      # Sanath Jayasuriya(93p), Muttiah Muralitharan(95bwl)
    "newzealand2010s",    # Brendon McCullum, Kane Williamson, Trent Boult(92bwl)
]

# ── THE KEY INSIGHT: Math.random() INTERCEPTION ───────────────────────────────
# The spin picks squad like: vo[Math.floor(Math.random() * vo.length)]
# vo.length = 38
# So if we return X/38 <= Math.random() < (X+1)/38, squad at index X is picked
#
# For westindies1980s (index 24 in ALL_SQUADS list):
#   return 24/38 = 0.6315...
# For southafrica2010s (index 18):
#   return 18/38 = 0.4736...

def squad_index(squad_id):
    return ALL_SQUADS.index(squad_id)

# ── MATH.RANDOM OVERRIDE SCRIPT ───────────────────────────────────────────────
def make_intercept_script(target_squad_ids):
    """
    Create a JS script that overrides Math.random() to control squad selection.
    
    How it works:
    - Tracks call count
    - Call #1 (squad selection): returns value to force desired squad
    - Calls during animation (2-16): returns truly random values
    - Simulation calls: returns truly random (or fixed seed for prediction)
    """
    # Build the list of target squad indices
    indices = [squad_index(sid) for sid in target_squad_ids if sid in ALL_SQUADS]
    n_squads = len(ALL_SQUADS)  # 38
    
    return f"""
(function() {{
    const TARGET_INDICES = {json.dumps(indices)};
    const N_SQUADS = {n_squads};
    const origRandom = Math.random.bind(Math);
    
    // Track how many times we've been called per "spin"
    // The game calls Math.random() ONCE to pick the squad
    // Then calls it ~15 more times for the animation reel
    // Then calls it many times during simulation
    
    let callCount = 0;
    let squadPickCount = 0;  // which spin # we're on
    let forceSquadCall = false;
    
    // Expose a function so our Playwright script can trigger a new "force"
    window.__forceNextSpin = function() {{
        forceSquadCall = true;
        callCount = 0;
    }};
    
    window.__spinCount = 0;
    
    Math.random = function() {{
        callCount++;
        
        // The FIRST call in a spin sequence picks the squad
        // We detect this by: forceSquadCall flag is set
        if (forceSquadCall && callCount === 1) {{
            forceSquadCall = false;
            window.__spinCount++;
            
            // Cycle through target squads
            const idx = TARGET_INDICES[(window.__spinCount - 1) % TARGET_INDICES.length];
            const val = (idx + 0.5) / N_SQUADS;  // middle of the squad's bucket
            console.log('[INTERCEPT] Forcing squad index ' + idx + ' -> val=' + val.toFixed(4));
            return val;
        }}
        
        return origRandom();
    }};
    
    console.log('[INTERCEPT] Math.random overridden. Target squads: {json.dumps(target_squad_ids)}');
}})();
"""

# ── DOM READERS (proven from v7) ──────────────────────────────────────────────
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
            else if (/^(BATTER|BOWLER|ALL-ROUNDER|WK|WICKET-KEEPER|AR)$/i.test(t)) role = t.toUpperCase();
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
        return await page.evaluate(
            """([txt, exact]) => {
                const want = txt.toUpperCase();
                for (const b of document.querySelectorAll('button')) {
                    const t = (b.innerText||'').trim().toUpperCase();
                    const ok = exact ? t === want : t.includes(want);
                    if (ok && !b.disabled) { b.click(); return true; }
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

NAME_RE = re.compile(r"^[A-Z][A-Z .''\u2019\-]+$")
SKIP = {"WK","BAT","BWL","AR","THE DRAFT","ALL ROUNDER","WICKETKEEPER"}

async def draft_truth(page):
    txt = await body_text(page)
    low = txt.split("Fill all 11 positions.", 1)
    seg = low[1] if len(low) > 1 else txt
    for stop in ("RE-ROLL", "SPIN", "SIMULATE", "START"):
        seg = seg.split(stop, 1)[0]
    lines = [l.strip() for l in seg.splitlines()]
    pos_map = {}
    for i in range(len(lines) - 1):
        if re.fullmatch(r"(10|11|[1-9])", lines[i]) and NAME_RE.fullmatch(lines[i+1]) \
                and lines[i+1] not in SKIP:
            pos_map[int(lines[i])] = lines[i+1]
    m = re.search(r"(\d{1,2})\s*/\s*11", txt)
    cnt = int(m.group(1)) if m else len(pos_map)
    return cnt, pos_map

async def choose_position(page, prefer_order):
    chosen = None
    for _ in range(20):
        btns = await page.evaluate("""() => {
            const out = [];
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim();
                if (!/^(10|11|[1-9])$/.test(t)) continue;
                const n = parseInt(t);
                if (n < 1 || n > 11) continue;
                const style = b.getAttribute('style')||'';
                const m = style.match(/opacity:\\s*([\\d.]+)/);
                out.push({n, dis: !!b.disabled, op: m ? parseFloat(m[1]) : 1});
            }
            return out;
        }""")
        usable = [x for x in btns if not x['dis'] and x['op'] > 0.85]
        if usable:
            for pref in prefer_order:
                if any(x['n'] == pref for x in usable):
                    ok = await page.evaluate("""(n) => {
                        for (const b of document.querySelectorAll('button')) {
                            const t = (b.innerText||'').trim();
                            if (t === String(n)) {
                                const s = b.getAttribute('style')||'';
                                const m = s.match(/opacity:\\s*([\\d.]+)/);
                                const op = m ? parseFloat(m[1]) : 1;
                                if (!b.disabled && op > 0.85) { b.click(); return true; }
                            }
                        }
                        return false;
                    }""", pref)
                    if ok:
                        chosen = pref
                        break
            if chosen is not None:
                break
            n = usable[0]['n']
            await page.evaluate("""(n) => {
                for (const b of document.querySelectorAll('button'))
                    if ((b.innerText||'').trim() === String(n) && !b.disabled) { b.click(); return; }
            }""", n)
            chosen = n
            break
        await asyncio.sleep(0.25)
    return chosen

# ── OPTIMAL PICKS FROM KNOWN SQUADS ──────────────────────────────────────────
# Pre-computed best picks per squad (from vo_squads.js data)
# Format: squad_id -> [{name, slot_pref}, ...]
SQUAD_PICKS = {
    "westindies1980s": [
        # Viv Richards(96p), Gordon Greenidge(88p), Desmond Haynes, Clive Lloyd
        # Malcolm Marshall(96bwl), Joel Garner(92bwl), Michael Holding(90bwl), Andy Roberts(88bwl)
        {"top7": ["Viv Richards", "Gordon Greenidge", "Desmond Haynes", "Clive Lloyd",
                  "Jeff Dujon"],  # WK
         "bot4": ["Malcolm Marshall", "Joel Garner", "Michael Holding", "Andy Roberts"]},
    ],
    "southafrica2010s": [
        {"top7": ["AB de Villiers", "Heinrich Klaasen", "Faf du Plessis", "Quinton de Kock",
                  "David Miller", "JP Duminy", "Chris Morris"],
         "bot4": ["Dale Steyn", "Kagiso Rabada", "Imran Tahir", "Lungi Ngidi"]},
    ],
    "england2010s": [
        {"top7": ["Jos Buttler", "Jonny Bairstow", "Jason Roy", "Ben Stokes",
                  "Eoin Morgan", "Alex Hales", "Moeen Ali"],
         "bot4": ["Jofra Archer", "Mark Wood", "Adil Rashid", "Chris Woakes"]},
    ],
}

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding='utf-8'))
        except: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding='utf-8')

async def shot(page, name):
    try: await page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)
    except: pass

# ── THE BEST PLAYER SELECTION LOGIC ──────────────────────────────────────────
def pick_best(squad, slot, taken):
    """Pick best player for slot using actual ratings."""
    is_bwl = slot >= 8
    avail = [c for c in squad if c['name'] not in taken and c.get('enabled', True)]
    avail = [c for c in avail if c['lo'] <= slot <= c['hi']]
    if not avail:
        avail = [c for c in squad if c['name'] not in taken and c.get('enabled', True)]
    if not avail:
        return None

    if is_bwl:
        return max(avail, key=lambda c: c['bl'] * 0.9 + c['p'] * 0.1)
    else:
        # For top-7: maximize POW*0.6 + BAT*0.4 (speed-focused)
        return max(avail, key=lambda c: c['p'] * 0.6 + c['b'] * 0.4)

# ── WIN/RESULT DETECTION ──────────────────────────────────────────────────────
WIN_KW  = ("500 CLUB","YOU DID IT","CHASED","PERFECT","CONGRATULATIONS","HISTORY")
FAIL_KW = ("FELL SHORT","HEARTBREAK","ALL OUT","SO CLOSE","DENIED","COLLAPSED","LOST")

async def wait_result(page, sid, baseline_txt, timeout=120):
    t0 = time.time()
    base_lines = {l.strip() for l in baseline_txt.splitlines()}
    last_novel = ""
    while time.time() - t0 < timeout:
        cur = await body_text(page)
        novel = "\n".join(l for l in cur.splitlines()
                          if l.strip() and l.strip() not in base_lines)
        up = novel.upper()

        if "FAST" in up:
            await click_btn(page, "FAST", exact=True)
        if "SKIP" in up:
            await click_btn(page, "SKIP TO END")
            await asyncio.sleep(3)

        m  = re.search(r"\b(\d{3,4})\s*/\s*(\d)\b", novel)
        ov = re.search(r"(\d{1,3}\.\d)\s*OVER", up)
        ctx = any(k in up for k in ("OVER","BALL","WICKET","SHORT"))

        win  = (any(k in up for k in WIN_KW) and ctx) or "500 CLUB" in up
        fail = any(k in up for k in FAIL_KW) or (m and ctx and int(m.group(1)) < 500)

        if win or fail:
            await shot(page, f"s{sid}_result")
            sc = int(m.group(1)) if m else (500 if win else None)
            return {"score": sc, "wkts": int(m.group(2)) if m else None,
                    "overs": ov.group(1) if ov else None,
                    "win": bool(win or (sc and sc >= 500)),
                    "timeout": False, "snippet": novel[:300]}
        await asyncio.sleep(0.8)

    await shot(page, f"s{sid}_timeout")
    return {"score": None, "win": False, "timeout": True}

# ── MAIN INTERCEPTION SESSION ─────────────────────────────────────────────────
async def intercept_session(pw, sid):
    """
    Uses Math.random() interception to FORCE specific squads during spin.
    This guarantees we see elite players every spin.
    """
    rec = {"session": sid, "ts": datetime.now().isoformat(),
           "drafted": [], "success": False, "method": "intercept"}

    browser = await pw.chromium.launch(headless=False)
    ctx = await browser.new_context(viewport={"width": 480, "height": 1000})

    # INJECT the Math.random override BEFORE the page loads
    intercept_js = make_intercept_script(TARGET_SQUADS)
    await ctx.add_init_script(script=intercept_js)

    page = await ctx.new_page()
    try:
        log(f"  Loading 500-0.com with Math.random() interception active...")
        await page.goto("https://500-0.com", wait_until="domcontentloaded")
        await asyncio.sleep(2.5)

        # Select EASY mode
        await click_btn(page, "EASY")
        await asyncio.sleep(0.4)
        await click_btn(page, "DRAFT")
        await asyncio.sleep(2.0)

        assigned, taken = {}, set()
        spin_no = 0

        for slot in range(1, 12):
            spin_no += 1
            is_bwl = slot >= 8
            log(f"\n  Slot {slot}/11 ({'BWL' if is_bwl else 'BAT'})")

            # FORCE NEXT SPIN to our target squad
            await page.evaluate("() => window.__forceNextSpin()")

            # Click SPIN
            ok = await click_btn(page, "SPIN", exact=True)
            if not ok:
                await asyncio.sleep(1.5)
                ok = await click_btn(page, "SPIN", exact=True)
            await asyncio.sleep(4)  # wait for animation

            # Read squad
            squad = await page.evaluate(READ_SQUAD_JS)
            squad_name = await page.evaluate("() => document.querySelector('h2,h3,[class*=squad-name],[class*=squadName]')?.textContent || ''")
            log(f"  Squad shown: {squad_name.strip() or '?'} | Players: {[c['name'] for c in squad[:4]]}")

            if not squad:
                log("  No squad! Retrying spin...")
                continue

            # Pick best player for this slot
            player = pick_best(squad, slot, taken)
            if not player:
                log(f"  No valid player for slot {slot}!")
                continue

            log(f"  Pick: {player['name']} [b={player['b']} p={player['p']} bl={player['bl']}]")
            await shot(page, f"s{sid}_slot{slot:02d}_squad")

            # Click the player
            clicked = await click_player(page, player['name'])
            if not clicked:
                # Fallback: click first available
                for c in squad:
                    if c['name'] not in taken:
                        clicked = await click_player(page, c['name'])
                        if clicked:
                            player = c
                            break

            if not clicked:
                log(f"  Click failed for {player['name']}")
                continue

            # Handle position popup
            st_free = [q for q in range(1,12) if q not in assigned]
            prefer = [slot] + [x for x in st_free if x != slot]
            pos = await choose_position(page, prefer)
            log(f"    Position chosen: {pos}")

            # Verify registration
            registered = False
            for _ in range(15):
                await asyncio.sleep(0.5)
                cnt, pos_map = await draft_truth(page)
                if player['name'].upper() in pos_map.values():
                    registered = True
                    break

            if registered:
                real_q = next(q for q,nm in pos_map.items() if nm == player['name'].upper())
                assigned[real_q] = player
                taken.add(player['name'])
                rec["drafted"].append({"slot": real_q, "name": player['name'],
                                       "b": player['b'], "p": player['p'], "bl": player['bl'],
                                       "role": player.get('role','')})
                log(f"  ✓ {player['name']} → pos {real_q}")
            else:
                log(f"  ✗ {player['name']} did NOT register")

        # Check draft count
        cnt, _ = await draft_truth(page)
        log(f"\n  Draft complete: {cnt}/11 filled")
        if cnt < 11:
            log(f"  WARNING: only {cnt}/11 filled!")

        # Compute team quality
        bat7 = [assigned[q] for q in sorted(assigned) if q <= 7]
        bwl4 = [assigned[q] for q in sorted(assigned) if q >= 8]
        abat = sum(p['b'] for p in bat7) / max(1, len(bat7))
        apow = sum(p['p'] for p in bat7) / max(1, len(bat7))
        abwl = sum(p['bl'] for p in bwl4) / max(1, len(bwl4))
        wk   = any('WK' in p.get('role','') for p in assigned.values())
        n70  = sum(1 for p in assigned.values() if p['bl'] >= 70)

        # Expected overs using f6 formula:
        # N = (abat-86) + (apow-89) + (abwl-90)
        N = max(0, (abat - 86) + (apow - 89) + (abwl - 90))
        B = min(1.0, N / 16.5)
        exp_balls = round(282 - B * 72)
        exp_overs = exp_balls / 6

        log(f"\n  Team: BAT={abat:.1f} POW={apow:.1f} BWL={abwl:.1f} WK={wk} n70={n70}")
        log(f"  Expected balls: {exp_balls} ({exp_overs:.1f} overs) | Speed bonus N={N:.2f} B={B:.3f}")

        rec["metrics"] = {"avg_bat": round(abat,2), "avg_pow": round(apow,2),
                          "avg_bwl": round(abwl,2), "wk": wk, "n70": n70,
                          "exp_balls": exp_balls, "exp_overs": round(exp_overs,1)}

        # Simulate
        await shot(page, f"s{sid}_presim")
        baseline = await body_text(page)
        await asyncio.sleep(1.0)

        sim_clicked = False
        for label in ("SIMULATE", "START", "PLAY MATCH"):
            if await click_btn(page, label, exact=True):
                sim_clicked = True
                break
        if not sim_clicked:
            sim_clicked = await click_btn(page, "SPIN", exact=True)

        log(f"  Simulation started: {sim_clicked}")
        if not sim_clicked:
            return None

        res = await wait_result(page, sid, baseline)
        rec.update(res)
        rec["success"] = bool(res.get("win"))

        if res.get("win"):
            log(f"\n  🏆 500! Score={res['score']} in {res.get('overs','?')} overs (exp={exp_overs:.1f})")
        else:
            log(f"\n  ❌ Score={res['score']} | timeout={res['timeout']}")

    except Exception as e:
        import traceback; traceback.print_exc()
        rec["error"] = str(e)
    finally:
        try: await browser.close()
        except: pass

    return rec

# ── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    total = wins = 0
    log("=" * 70)
    log("  500-0.com SPIN INTERCEPTOR - Forces elite squads every spin")
    log("  Math.random() overridden to control squad selection")
    log("  Target squads: " + ", ".join(TARGET_SQUADS[:4]) + "...")
    log("=" * 70)

    async with async_playwright() as pw:
        while True:
            try:
                total += 1
                log(f"\n{'='*70}\n  RUN #{total} | Wins: {wins}\n{'='*70}")
                rec = await intercept_session(pw, total)
                if rec:
                    save_run(rec)
                    if rec.get("success"):
                        wins += 1
                        log(f"\n🏆🏆🏆 WIN #{wins}! Score={rec.get('score')} "
                            f"Overs={rec.get('overs')} 🏆🏆🏆")
                    else:
                        log(f"  Score: {rec.get('score')} | Wins: {wins}/{total}")
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"OUTER ERROR: {e}")
                await asyncio.sleep(3)

    log(f"\nFINAL: {wins} wins in {total} runs")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped")
