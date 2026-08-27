"""
500/0 BOT v8 - SPEED OPTIMIZED (target <38 overs / 228 balls)
=============================================================
Goal: Chase 500 in LESS THAN 38 overs (228 balls).

Key strategy change vs v7:
  - MUCH higher POW threshold (POW drives run-rate / over-rate)
  - Score is determined by: BAT = staying power, POW = scoring speed
  - For fastest chase: maximize POW*0.7 + BAT*0.3 for top-7
  - Reject squads unless they have GOLD-tier batter/WK (POW >= 90, BAT >= 85)

Speed thresholds for sub-38 overs:
  top-7 avg BAT >= 88   (sum 616)
  top-7 avg POW >= 92   (sum 644) ← higher than v7's 89
  8-11  avg BWL >= 91   (sum 364)
  Must have: 2+ players with POW >= 94 (boundary hitters)
  Must have: 1 WK role

Target XI from leaderboard analysis (fastest templates):
  1. High-POW opener:    Rohit(95), Travis Head(94), Chris Gayle(94), Sehwag(93)
  2. High-POW #2:        Rohit/Virat(94)/Sachin(88)/Chris Gayle(94)
  3. Anchor batter:      Virat Kohli(94), Viv Richards(96), Sachin(88), Lara(93)
  4. Power batter:       Viv Richards(96), AB de Villiers(98), Lara(93)
  5. Elite WK:           AB de Villiers(98 POW), Klaasen(95), Buttler(96)
  6. Power WK/bat:       Klaasen(95), Buttler(96), Adam Gilchrist(93)
  7. Hitter/AR:          Shahid Afridi(91), Lance Klusener(93), Glenn Maxwell(90)
  8. Elite BWL:          Wasim Akram(95), Malcolm Marshall(96)
  9. Elite BWL:          Muttiah Muralitharan(95), Warne(94), Rashid Khan(94)
  10. Elite BWL:          Muralitharan(95), Marshall(96), Ambrose(93)
  11. Elite BWL:          Muralitharan(95), Curtly Ambrose(93), Mitchell Starc(94)

RUN:  python bot_v8.py
STOP: Ctrl+C
"""

import asyncio, json, re, sys, pathlib, time
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── CONFIG ────────────────────────────────────────────────────────────────────
URL      = "https://500-0.com"
HEADLESS = False
BASE     = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v8.json"
SHOT_DIR = BASE / "screenshots_v8"; SHOT_DIR.mkdir(exist_ok=True)
LIVE_DIR = BASE / "live"; LIVE_DIR.mkdir(exist_ok=True)

# ── SPEED THRESHOLDS ──────────────────────────────────────────────────────────
# For sub-38-over chase (from leaderboard analysis of fastest teams):
# Keep BAT/BWL at proven win level, raise POW significantly
SUM_BAT = 602   # avg 86 × 7   (same as v7 proven winner threshold)
SUM_POW = 638   # avg 91 × 7   (raised — POW drives scoring rate)
SUM_BWL = 360   # avg 90 × 4   (same as v7)
MIN_POW94 = 1   # need ≥1 player with POW >= 94 (main boundary hitter)

# Optimistic fill assumptions (what we expect average future picks to give)
FILL_BAT, FILL_POW, FILL_BWL = 88, 91, 90


# ── SCORE WEIGHTING FOR SLOT SELECTION ────────────────────────────────────────
# For top-7: prioritize POW heavily (run rate > staying power)
def batter_score(p):
    return p['p'] * 0.65 + p['b'] * 0.35

def bowler_score(p):
    return p['bl'] * 0.90 + p['p'] * 0.10

# ── PLAYER KNOWLEDGE (for fallback + anchor gate) ─────────────────────────────
# These are confirmed from screenshots: real POW and BAT values
ELITE_POW = {  # players with POW >= 92
    "AB de Villiers", "Viv Richards", "Rohit Sharma", "Jos Buttler",
    "Heinrich Klaasen", "Travis Head", "Chris Gayle", "Shahid Afridi",
    "Lance Klusener", "Virat Kohli", "Brian Lara", "Adam Gilchrist",
    "Jonny Bairstow", "Jason Roy", "David Warner", "Sanath Jayasuriya",
    "MS Dhoni", "Virender Sehwag", "Glenn Maxwell",
}
ELITE_BWL = {  # players with BWL >= 92
    "Muttiah Muralitharan", "Wasim Akram", "Malcolm Marshall", "Shane Warne",
    "Curtly Ambrose", "Mitchell Starc", "Rashid Khan", "Waqar Younis",
    "Dale Steyn", "Lasith Malinga", "Joel Garner", "Jasprit Bumrah",
    "Shane Bond", "Jofra Archer",
}

# ── DOM READERS (identical to v7 — proven working) ────────────────────────────
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

async def read_squad(page):
    try:
        return await page.evaluate(READ_SQUAD_JS)
    except Exception:
        return []

async def wait_for_squad(page, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        sq = await read_squad(page)
        if len(sq) >= 8:
            return sq
        await asyncio.sleep(0.4)
    return []

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
    except Exception:
        return False

async def click_player(page, name):
    return await page.evaluate("""(name) => {
        for (const btn of document.querySelectorAll('button')) {
            const el = btn.querySelector('.text-sm.font-medium');
            if (el && (el.textContent||'').trim() === name) {
                const style = btn.getAttribute('style')||'';
                const m = style.match(/opacity:\\s*([\\d.]+)/);
                const op = m ? parseFloat(m[1]) : 1;
                if (!btn.disabled && op > 0.85) { btn.click(); return true; }
                return false;
            }
        }
        return false;
    }""", name)

async def body_text(page):
    try: return await page.evaluate("() => document.body.innerText")
    except: return ""

NAME_RE = re.compile(r"^[A-Z][A-Z .''\u2019\-]+$")
SKIP = {"WK","BAT","BWL","AR","THE DRAFT","ALL ROUNDER","WICKETKEEPER","FILL"}

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

# ── STRATEGY ENGINE ───────────────────────────────────────────────────────────
def slot_state(assigned):
    free  = [q for q in range(1,12) if q not in assigned]
    top   = [q for q in free if q <= 7]
    bot   = [q for q in free if q >= 8]
    sbat  = sum(p['b'] for q,p in assigned.items() if q<=7)
    spow  = sum(p['p'] for q,p in assigned.items() if q<=7)
    sbwl  = sum(p['bl'] for q,p in assigned.items() if q>=8)
    wk    = any(p.get('wk') for p in assigned.values())
    n94   = sum(1 for p in assigned.values() if p['p'] >= 94)
    n70   = sum(1 for p in assigned.values() if p['bl'] >= 70)
    return dict(free=free,top=top,bot=bot,sbat=sbat,spow=spow,sbwl=sbwl,wk=wk,n94=n94,n70=n70)

def feasible(st, c, q):
    """Can we still hit speed thresholds if we pick c at q?"""
    kt = len(st['top']) - (1 if q<=7 else 0)
    kb = len(st['bot']) - (1 if q>=8 else 0)
    ebat = st['sbat'] + (c['b'] if q<=7 else 0) + kt*FILL_BAT
    epow = st['spow'] + (c['p'] if q<=7 else 0) + kt*FILL_POW
    ebwl = st['sbwl'] + (c['bl'] if q>=8 else 0) + kb*FILL_BWL
    return ebat >= SUM_BAT and epow >= SUM_POW and ebwl >= SUM_BWL

def is_dead(assigned):
    st = slot_state(assigned)
    kt, kb = len(st['top']), len(st['bot'])
    wk_ok = st['wk'] or len(st['free']) >= 3
    return not (st['sbat']+kt*FILL_BAT>=SUM_BAT and st['spow']+kt*FILL_POW>=SUM_POW
                and st['sbwl']+kb*FILL_BWL>=SUM_BWL and wk_ok)

def choose_pick(squad, taken, assigned, need_wk=False):
    st = slot_state(assigned)
    best, best_score = None, None
    slots_filled = len(assigned)

    for c in squad:
        if c['name'] in taken or not c.get('enabled'): continue
        is_wk = 'WK' in (c.get('role') or '')
        is_bowler = 'BOWLER' in (c.get('role') or '') and not is_wk
        if need_wk and not is_wk and not st['wk']: continue

        for q in range(c['lo'], min(c['hi'],11)+1):
            if q not in st['free']: continue

            # Don't put pure bowlers in top-7 if there are still top-7 slots needed
            # (unless their lo > 7 anyway, meaning they CAN'T go in top-7)
            if is_bowler and q <= 7 and len(st['top']) > 0:
                # Only allow if we have no batter alternative for this squad
                has_batter_alt = any(
                    c2['lo'] <= 7 and 'BOWLER' not in (c2.get('role') or '')
                    for c2 in squad if c2['name'] not in taken and c2.get('enabled')
                )
                if has_batter_alt:
                    continue  # Skip: a batter is available, don't waste a top-7 slot

            if not feasible(st, c, q): continue
            wk_after = st['wk'] or is_wk or (len(st['free'])-1 >= 3)
            if not wk_after: continue

            if q <= 7:
                pick_score = batter_score(c)
            else:
                pick_score = bowler_score(c)

            wk_bonus  = 3.0 if (is_wk and not st['wk']) else 0.0
            pow_bonus = 2.0 if c['p'] >= 94 else (1.0 if c['p'] >= 90 else 0.0)
            # Bonus for elite bowlers in bowler slots
            bwl_bonus = 2.0 if (q >= 8 and c['bl'] >= 92) else 0.0

            # Power hitters bonus for top-3 slots (they face most balls)
            top3_bonus = 1.5 if (q <= 3 and c['p'] >= 92) else 0.0

            total = pick_score + wk_bonus + pow_bonus + bwl_bonus + top3_bonus

            if best_score is None or total > best_score:
                best_score = total
                best = (c, q)
    return best


# First-spin anchor: need at least one genuine elite BAT/WK/POW player
def squad_has_speed_anchor(squad):
    for c in squad:
        if not c.get('enabled'): continue
        if c['lo'] > 7: continue  # skip pure bowlers for anchor check
        # Gold tier WK (AB de Villiers, Klaasen, Buttler etc)
        if 'WK' in (c.get('role') or '') and c['b'] >= 84 and c['p'] >= 90:
            return True
        # Gold tier batter (Richards, Kohli, Gayle etc)
        if c['b'] >= 88 and c['p'] >= 88:
            return True
    return False

# ── POSITION POPUP ────────────────────────────────────────────────────────────
async def choose_position(page, prefer_order):
    """Click the best available position number button from the popup.
    Returns the number clicked, or None if no popup appeared."""
    chosen = None
    # Wait up to 5 seconds for the popup to appear
    for attempt in range(20):
        btns = await page.evaluate("""() => {
            const out = [];
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim();
                // Match 1 or 2 digit numbers (1-11)
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
            # If only one option, just click it
            if len(usable) == 1:
                n = usable[0]['n']
                await page.evaluate("""(n) => {
                    for (const b of document.querySelectorAll('button')) {
                        const t = (b.innerText||'').trim();
                        if (t === String(n) && !b.disabled) { b.click(); return; }
                    }
                }""", n)
                chosen = n
                break

            # Try preferred positions first
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

            # No preferred usable — take first usable slot
            if usable:
                n = usable[0]['n']
                await page.evaluate("""(n) => {
                    for (const b of document.querySelectorAll('button'))
                        if ((b.innerText||'').trim() === String(n) && !b.disabled) { b.click(); return; }
                }""", n)
                chosen = n
                break

        await asyncio.sleep(0.25)
    return chosen


# ── RESULT DETECTION ──────────────────────────────────────────────────────────
WIN_KW  = ("500 CLUB","YOU DID IT","CHASED","PERFECT CHASE","HISTORY","CONGRATULATIONS")
FAIL_KW = ("FELL SHORT","HEARTBREAK","ALL OUT","SO CLOSE","DENIED","AGONY","CRUEL","LOST","COLLAPSED")

async def wait_result(page, sid, baseline_txt, timeout=120):
    t0 = time.time()
    base_lines = {l.strip() for l in baseline_txt.splitlines()}
    last_novel = ""
    while time.time() - t0 < timeout:
        cur = await body_text(page)
        novel = "\n".join(l for l in cur.splitlines()
                          if l.strip() and l.strip() not in base_lines)
        up = novel.upper()
        if up != last_novel:
            last_novel = up

        # Click FAST button to speed through animation
        if "FAST" in up:
            await click_btn(page, "FAST", exact=True)
        if "SKIP" in up:
            await click_btn(page, "SKIP TO END")
            await asyncio.sleep(3)

        m  = re.search(r"\b(\d{3,4})\s*/\s*(\d)\b", novel)
        ov = re.search(r"(\d{1,3}\.\d)\s*OVER", up)
        balls_match = re.search(r"(\d{2,3})\s*BALL", up)
        ctx = ("OVER" in up or "BALL" in up or "WICKET" in up or "SHORT" in up or ov is not None)

        win_hit = ((any(k in up for k in WIN_KW) or
                    bool(re.search(r"\b500\s*/\s*0\b", novel))) and ctx) or "500 CLUB" in up
        fail_hit = (any(k in up for k in FAIL_KW) or
                    (m is not None and ctx and int(m.group(1)) < 500))

        if win_hit or fail_hit:
            try:
                await page.screenshot(path=str(SHOT_DIR / f"s{sid}_result.png"), full_page=True)
            except: pass
            score = int(m.group(1)) if m else (500 if win_hit else None)
            wkts  = int(m.group(2)) if m else None
            overs = ov.group(1) if ov else None
            balls = int(balls_match.group(1)) if balls_match else None
            return {
                "score": score, "wkts": wkts, "overs": overs,
                "balls_detected": balls,
                "win": bool(win_hit or (score is not None and score >= 500)),
                "timeout": False,
                "result_snippet": novel[:400],
            }
        await asyncio.sleep(0.8)

    try:
        await page.screenshot(path=str(SHOT_DIR / f"s{sid}_timeout.png"), full_page=True)
    except: pass
    return {"score":None,"win":False,"timeout":True,"result_snippet":last_novel[:300]}

# ── LOG HELPER ────────────────────────────────────────────────────────────────
def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")

async def shot(page, name):
    try: await page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)
    except: pass

# ── DRAFT SESSION ─────────────────────────────────────────────────────────────
async def draft_session(pw, sid):
    rec = {"session": sid, "ts": datetime.now().isoformat(),
           "reloads": 0, "reroll_used": False,
           "drafted": [], "success": False}
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(viewport={"width": 480, "height": 1000})
    page = await ctx.new_page()
    try:
        # ── PHASE 1: Find good first squad (anchor gate) ──────────────────
        anchored = False
        for attempt in range(60):  # more attempts for speed gate
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2.2)
            await click_btn(page, "EASY")
            await asyncio.sleep(0.4)
            await click_btn(page, "DRAFT")
            await asyncio.sleep(1.8)
            ok = await click_btn(page, "SPIN", exact=True)
            if not ok:
                await asyncio.sleep(1.2)
                ok = await click_btn(page, "SPIN", exact=True)
                if not ok:
                    rec["reloads"] += 1
                    continue
            squad = await wait_for_squad(page, timeout=12)
            if not squad:
                rec["reloads"] += 1
                continue
            if squad_has_speed_anchor(squad):
                anchored = True
                anchor = next(c for c in squad if c['lo']<=7 and
                              ((c['b']>=88 and c['p']>=88) or
                               ('WK' in (c.get('role') or '') and c['p']>=90)))
                log(f"  ANCHOR: {anchor['name']} [b={anchor['b']} p={anchor['p']}] after {rec['reloads']} reloads")
                break
            rec["reloads"] += 1
        if not anchored:
            log("  No speed anchor found in 60 attempts — proceeding with best available")

        # ── PHASE 2: Draft 11 slots ───────────────────────────────────────
        assigned, taken = {}, set()
        rerolls_left = 1
        stall = 0

        while True:
            cnt, pos_map = await draft_truth(page)
            # Re-sync assigned with page truth
            assigned = {}
            for q, nm in pos_map.items():
                for d in rec["drafted"]:
                    if d["name"].upper() == nm:
                        assigned[q] = {"name": d["name"], "b": d["b"],
                                       "p": d["p"], "bl": d["bl"],
                                       "wk": 'WK' in (d.get("role") or "")}
            if cnt >= 11:
                break

            spin_no = cnt + 1
            squad = await read_squad(page)
            avail = [c for c in squad if c['name'] not in taken and c.get('enabled')]
            if len(avail) < 2:
                ok = await click_btn(page, "SPIN", exact=True)
                if not ok:
                    await asyncio.sleep(1.0)
                    ok = await click_btn(page, "SPIN", exact=True)
                squad = await wait_for_squad(page)
                avail = [c for c in squad if c['name'] not in taken and c.get('enabled')]

            st = slot_state(assigned)
            need_wk = (not st['wk']) and spin_no >= 8

            choice = choose_pick(squad, taken, assigned, need_wk)

            # ── REROLL LOGIC ──────────────────────────────────────────────
            # Use reroll if: early spin (<= 4) and no strong POW batter available
            if rerolls_left > 0 and spin_no <= 4 and not need_wk:
                pow_ok = any(c['p'] >= 90 and c['lo'] <= 7 and c['name'] not in taken
                             for c in squad if c.get('enabled'))
                if not pow_ok:
                    log(f"  spin{spin_no}: no POW>=90 batter -> REROLL")
                    if await click_btn(page, "RE-ROLL"):
                        rerolls_left -= 1
                        rec["reroll_used"] = True
                        await asyncio.sleep(2.8)
                        squad = await wait_for_squad(page)
                        choice = choose_pick(squad, taken, assigned, need_wk)

            # Also use reroll if no valid candidate at all
            if choice is None and rerolls_left > 0 and not need_wk:
                log(f"  spin{spin_no}: no viable pick -> REROLL")
                if await click_btn(page, "RE-ROLL"):
                    rerolls_left -= 1
                    rec["reroll_used"] = True
                    await asyncio.sleep(2.8)
                    squad = await wait_for_squad(page)
                    choice = choose_pick(squad, taken, assigned, need_wk)

            if choice is None:
                # Forced pick — take best available ignoring feasibility
                cand = [c for c in squad if c['name'] not in taken and c.get('enabled')]
                if not cand:
                    stall += 1
                    if stall > 3:
                        log("  stall dead-end — aborting")
                        return None
                    await asyncio.sleep(1.5)
                    continue

                fb_pick, fb_q, fb_score = None, None, None
                for c in cand:
                    for q in [x for x in range(c['lo'], min(c['hi'],11)+1) if x in st['free']]:
                        sc = batter_score(c) if q<=7 else bowler_score(c)
                        if fb_score is None or sc > fb_score:
                            fb_score, fb_pick, fb_q = sc, c, q
                if fb_pick:
                    choice = (fb_pick, fb_q)
                    log(f"  spin{spin_no}: FORCED pick {fb_pick['name']}")
                else:
                    choice = (cand[0], st['free'][0])

            c, q_pref = choice
            log(f"  spin{spin_no}: {c['name']} -> pos{q_pref} [b={c['b']} p={c['p']} bl={c['bl']}"
                f"{' WK' if 'WK' in (c.get('role') or '') else ''}]")

            clicked = await click_player(page, c['name'])
            pos_chosen = None
            if clicked:
                await asyncio.sleep(0.4)
                pos_chosen = await choose_position(
                    page, [q_pref] + [x for x in range(1,12) if x != q_pref])
                log(f"    position chosen: {pos_chosen}")
            else:
                stall += 1

            # Verify registration
            registered = False
            for _ in range(14):
                await asyncio.sleep(0.5)
                cnt2, pos_map2 = await draft_truth(page)
                if c['name'].upper() in pos_map2.values():
                    registered = True
                    break

            if not registered:
                stall += 1
                log(f"  pick did NOT register (stall={stall})")
                if stall > 3:
                    return None
                continue

            stall = 0
            real_q = next(q for q,nm in pos_map2.items() if nm == c['name'].upper())
            if real_q != q_pref:
                log(f"  (assigned to pos{real_q} instead of {q_pref})")

            assigned[real_q] = {"name": c['name'], "b": c['b'], "p": c['p'],
                                 "bl": c['bl'], "wk": 'WK' in (c.get('role') or '')}
            taken.add(c['name'])
            rec["drafted"].append({"pos": real_q, "name": c['name'],
                                   "b": c['b'], "p": c['p'], "bl": c['bl'],
                                   "role": c.get('role','')})

            # Dead-end check
            if len(assigned) < 11 and is_dead(assigned):
                log("  team optimistically infeasible for speed target — aborting")
                return None

        # ── PHASE 3: Compute team metrics + simulate ──────────────────────
        cnt, _ = await draft_truth(page)
        if cnt < 11:
            log(f"  page says {cnt}/11 — aborting")
            return None

        bat7  = [assigned[q] for q in sorted(assigned) if q <= 7]
        bwl4  = [assigned[q] for q in sorted(assigned) if q >= 8]
        abat  = sum(p['b'] for p in bat7) / max(1, len(bat7))
        apow  = sum(p['p'] for p in bat7) / max(1, len(bat7))
        abwl  = sum(p['bl'] for p in bwl4) / max(1, len(bwl4))
        n94   = sum(1 for p in assigned.values() if p['p'] >= 94)
        n70   = sum(1 for p in assigned.values() if p['bl'] >= 70)
        has_wk = any(p['wk'] for p in assigned.values())

        speed_tier = (has_wk and n70 >= 3 and abat >= 88 and apow >= 92 and abwl >= 91 and n94 >= 2)
        log(f"  XI: BAT={abat:.1f} POW={apow:.1f} BWL={abwl:.1f} n94={n94} wk={has_wk}"
            f" => {'SPEED TIER (<38 overs)' if speed_tier else 'standard tier'}")

        rec["metrics"] = {"avg_bat_top7": round(abat,2), "avg_pow_top7": round(apow,2),
                          "avg_bwl_8_11": round(abwl,2), "n94_pow": n94,
                          "n70_bwl": n70, "has_wk": has_wk, "speed_tier": speed_tier}

        baseline = await body_text(page)
        await asyncio.sleep(1.0)
        await shot(page, f"s{sid}_presim")

        # Start simulation
        sim_clicked = False
        for label in ("SIMULATE", "START", "PLAY MATCH", "CHASE"):
            if await click_btn(page, label, exact=True):
                sim_clicked = True
                break
        if not sim_clicked:
            sim_clicked = await click_btn(page, "SPIN", exact=True)
            if sim_clicked:
                log("  (no SIMULATE button - used SPIN to start)")

        log(f"  simulation started: {sim_clicked}")
        if not sim_clicked:
            return None

        res = await wait_result(page, sid, baseline, timeout=120)
        rec.update(res)
        rec["success"] = bool(res.get("win"))

        # Report
        if res.get("win"):
            overs_str = res.get("overs", "?")
            log(f"  🏆 500 CLUB! Score={res.get('score')} in {overs_str} overs")
        else:
            log(f"  ❌ Score={res.get('score')} wkts={res.get('wkts')} timeout={res.get('timeout')}")

    except Exception as e:
        import traceback; traceback.print_exc()
        rec["error"] = str(e)
    finally:
        try: await browser.close()
        except: pass

    return rec

# ── MAIN LOOP ─────────────────────────────────────────────────────────────────
async def main():
    import os
    total = wins = speed_wins = aborts = 0
    log("=" * 65)
    log("  BOT v8 - SPEED OPTIMIZED (target <38 overs)")
    log("  Drafting to maximize POW sum => fastest chase possible")
    log("=" * 65)

    async with async_playwright() as pw:
        while True:
            try:
                total += 1
                log(f"\n{'='*65}\n  DRAFT #{total} | wins: {wins} | speed-wins: {speed_wins}\n{'='*65}")
                rec = None
                for retry in range(5):
                    rec = await draft_session(pw, total)
                    if rec is not None:
                        break
                    aborts += 1
                    log("  session aborted — retrying")

                if rec is None:
                    log("  All retries failed, continuing to next draft")
                    continue

                save_run(rec)

                if rec.get("success"):
                    wins += 1
                    m = rec.get("metrics", {})
                    if m.get("speed_tier"):
                        speed_wins += 1
                    log(f"\n{'#'*65}\n  WIN #{wins}! Score={rec.get('score')} "
                        f"overs={rec.get('overs')} speed_tier={m.get('speed_tier')}\n{'#'*65}")
                else:
                    log(f"  Score: {rec.get('score')} | Total wins: {wins}/{total}")

                await asyncio.sleep(2)

            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"  OUTER ERROR: {e}")
                await asyncio.sleep(3)

    log(f"\nFINAL: {wins} wins / {total} drafts | speed-wins (<38ov): {speed_wins} | aborted: {aborts}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user")
