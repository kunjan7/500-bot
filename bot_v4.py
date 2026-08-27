"""
500/0 BOT v4 - MARGIN-OPTIMIZED GRINDER (engine-decoded)
=========================================================
Decoded from app.js f6()/n6():
  tier-1  : wk AND nbowl>=3 AND batAvg(top7)>=86 AND powAvg>=89 AND bwlAvg(bot4)>=90
            -> 70% win / 30% 496-499 choke
  WIN     : chase must END >500 (exactly 500 => rewritten to 499 FAIL)
  SPEED   : N = (batAvg-86)+(powAvg-89)+(bwlAvg-90);  B=min(N/16.5,1)
            balls = clamp(282 - 72*B + U(-6,6), 204, 300)
            N=0 -> ~47 overs | N>=9.6 guarantees <=40 ov | N>=12 -> ~35-37 ov
  => strategy: maximize margin N, not bare qualification.

Leaderboard: setting localStorage['five-hundred-handle'] makes the site
auto-POST every result (worker /submit). We set 'kunjan####' once.

RUN: python bot_v4.py
env: MAX_DRAFTS  (default 48)      STOP_ON_WIN   (default 1)
     FAST_WIN_ONLY (default 1 -> keep going until a <40 over win)
     HANDLE_BASE (default kunjan)   SPIN1_MIN_BP (default 168)
"""

import asyncio, json, re, sys, time, random
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL      = "https://500-0.com"
BASE     = Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v4.json"
SHOT_DIR = BASE / "shots_v4"; SHOT_DIR.mkdir(exist_ok=True)
LIVE_DIR = BASE / "live"
HEADLESS = False

THR_BAT, THR_POW, THR_BWL = 602, 623, 360          # sum form of averages
W_BAT, W_POW, W_BWL = 1/7, 1/7, 1/4                # avg-margin weight per point

# TYPPP merged global positions (user-provided priority lists)
TYPPP = {
 "Rashid Khan":[9,8],"Rahmanullah Gurbaz":[1,2],"Shane Warne":[8,9,10],
 "Michael Bevan":[7,6,5],"Glenn McGrath":[10,11],"Ricky Ponting":[2,3,4],
 "Adam Gilchrist":[2,1,3],"Andrew Symonds":[6],"Mitchell Starc":[9,10,11],
 "Glenn Maxwell":[7,6,5],"David Warner":[2,1],"Steve Smith":[4],
 "Travis Head":[1,2],"Pat Cummins":[8],"Shakib Al Hasan":[5,4,3],
 "Soumya Sarkar":[1,2,3],"Kevin Pietersen":[4,3],"Andrew Flintoff":[6,7],
 "Marcus Trescothick":[2],"Jos Buttler":[6,7,5],"Jonny Bairstow":[2,1],
 "Jofra Archer":[11,10,9],"Eoin Morgan":[5,6],"Ben Stokes":[7],
 "Harry Brook":[4,3,5],"Sachin Tendulkar":[1,2,4],"MS Dhoni":[7,6,5],
 "Virender Sehwag":[1,2],"Yuvraj Singh":[4,5],"Virat Kohli":[3,2],
 "Rohit Sharma":[1,2],"Jasprit Bumrah":[9,10],"Suresh Raina":[4,5],
 "Shubman Gill":[2],"Boyd Rankin":[9,10],"Paul Stirling":[1,2],
 "Kevin O'Brien":[5,6,7],"Collins Obuya":[5,4,3],"Steve Tikolo":[4],
 "Ravindu Shah":[1,2],"Logan van Beek":[6,7],"Teja Nidamanuru":[4,5,6],
 "Bas de Leede":[3,4,5],"Chris Cairns":[7,6],"Martin Crowe":[5,3,4],
 "Mark Greatbatch":[1],"Shane Bond":[10,9],"Brendon McCullum":[7,6,1],
 "Daniel Vettori":[9,10],"Trent Boult":[10,11,9],"Martin Guptill":[1,2],
 "Kane Williamson":[3,4],"Mitchell Santner":[9,10],"Finn Allen":[1,2],
 "Daryl Mitchell":[4,5,3],"Glenn Phillips":[7],"Devon Conway":[2],
 "Wasim Akram":[8],"Waqar Younis":[9,10],"Imran Khan":[8],
 "Saeed Anwar":[1,2],"Saqlain Mushtaq":[10],"Shahid Afridi":[7,6,5],
 "Shoaib Akhtar":[11,9,10],"Mohammad Yousuf":[3,5],"Saeed Ajmal":[9,11,10],
 "Babar Azam":[1,2,3],"Umar Akmal":[6],"Mohammad Amir":[9],
 "Shaheen Afridi":[10,11,9],"Haris Rauf":[10],"Lance Klusener":[7,6],
 "Allan Donald":[10,9,11],"Shaun Pollock":[8],"Jacques Kallis":[3,5],
 "AB de Villiers":[5,4,3],"Makhaya Ntini":[10,9,11],"David Miller":[7,5,6],
 "Dale Steyn":[10,9,11],"Hashim Amla":[1,2],"Kagiso Rabada":[9,10],
 "Heinrich Klaasen":[6,5,4],"Rassie van der Dussen":[3],
 "Muttiah Muralitharan":[11,10,9],"Lasith Malinga":[10,9,11],
 "Sanath Jayasuriya":[1,2],"Kumar Sangakkara":[2,3,4],"Chaminda Vaas":[10,9,8],
 "Wanindu Hasaranga":[8,7],"Pathum Nissanka":[2,1],"Matheesha Pathirana":[11],
 "Viv Richards":[4,3],"Malcolm Marshall":[8,9,10],"Joel Garner":[11],
 "Gordon Greenidge":[1],"Brian Lara":[2,4,3],"Curtly Ambrose":[11,10,9],
 "Shivnarine Chanderpaul":[3],"Chris Gayle":[1,2],"Andre Russell":[7,6],
 "Jason Holder":[7],"Nicholas Pooran":[6,5,4],"Evin Lewis":[2,1],
}

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2), encoding="utf-8")

async def shot(page, name):
    try: await page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)
    except Exception: pass

# ---------------- JS ----------------
JS_COUNTER = """() => {
    const m = document.body.innerText.match(/(\\d+)\\s*\\/\\s*11/);
    return m ? parseInt(m[1]) : -1;
}"""

JS_CARDS = """() => {
    const out = [];
    const seen = new Set();
    for (const b of document.querySelectorAll('button')) {
        const t = b.innerText || '';
        if (!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue;
        if (!/BAT/.test(t)) continue;
        if (b.disabled) continue;
        const st = b.getAttribute('style') || '';
        const om = st.match(/opacity:\\s*([\\d.]+)/);
        if (om && parseFloat(om[1]) < 0.85) continue;
        const lines = t.split('\\n').map(s => s.trim()).filter(Boolean);
        let name = null, role = '', lo = 1, hi = 11, bb = 0, pp = 0, bl = 0;
        for (let i = 0; i < lines.length; i++) {
            const L = lines[i];
            if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) { role = L.toUpperCase(); continue; }
            const rm = L.match(/^(\\d{1,2})[-\\u2013](\\d{1,2})$/);
            if (rm) { lo = +rm[1]; hi = +rm[2]; continue; }
            if (/^BAT$/i.test(L) && i > 0 && /^\\d+$/.test(lines[i-1])) { bb = +lines[i-1]; continue; }
            if (/^POW$/i.test(L) && i > 0 && /^\\d+$/.test(lines[i-1])) { pp = +lines[i-1]; continue; }
            if (/^BWL$/i.test(L) && i > 0 && /^\\d+$/.test(lines[i-1])) { bl = +lines[i-1]; continue; }
        }
        if (!name) {
            for (const L of lines) {
                if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) continue;
                if (/^\\d/.test(L)) continue;
                if (/^(BAT|POW|BWL)$/i.test(L)) continue;
                name = L; break;
            }
        }
        if (!name || !role) continue;
        if (seen.has(name)) continue;
        seen.add(name);
        out.push({name, role, lo, hi, b: bb, p: pp, bl});
    }
    return out;
}"""

JS_POPUP_DIGITS = """() => {
    const dlg = [...document.querySelectorAll('div')].find(d =>
        d.className && String(d.className).includes('fixed') &&
        /Choose a batting position/i.test(d.textContent||'') && d.querySelector('button'));
    const root = dlg || document;
    const out = [];
    for (const b of root.querySelectorAll('button')) {
        const t = (b.textContent || '').trim();
        if (/^\\d{1,2}$/.test(t)) {
            const st = b.getAttribute('style') || '';
            const om = st.match(/opacity:\\s*([\\d.]+)/);
            out.push({n: parseInt(t), dis: !!b.disabled,
                      op: om ? parseFloat(om[1]) : 1});
        }
    }
    return out;
}"""

JS_CLICK_POSITION = """(n) => {
    const dlgs = [...document.querySelectorAll('div')]
        .filter(d => d.className && String(d.className).includes('fixed') &&
                     /Choose a batting position/i.test(d.textContent||''));
    const roots = dlgs.length ? dlgs : [document];
    for (const root of roots)
        for (const b of root.querySelectorAll('button'))
            if ((b.textContent||'').trim() === String(n) && !b.disabled) { b.click(); return true; }
    return false;
}"""

JS_CANCEL_POPUP = """() => {
    for (const b of document.querySelectorAll('button'))
        if ((b.textContent||'').trim().toLowerCase() === 'cancel') { b.click(); return true; }
    return false;
}"""

JS_CLICK_CARD = """(name) => {
    const want = name.replace(/\\s+/g, '').toUpperCase();
    for (const b of document.querySelectorAll('button')) {
        const t = (b.innerText || '').replace(/\\s+/g, '');
        if (t.toUpperCase().startsWith(want) && !b.disabled) { b.click(); return true; }
    }
    return false;
}"""

JS_XI_SLOTS = """() => {
    const t = document.body.innerText || '';
    const cutA = t.indexOf('Fill all 11 positions.');
    let seg = cutA >= 0 ? t.slice(cutA) : t;
    for (const stop of ['RE-ROLL', 'SPIN']) seg = seg.split(stop)[0];
    const lines = seg.split('\\n').map(s => s.trim());
    const out = {};
    for (let i = 0; i < lines.length - 1; i++) {
        if (/^(10|11|[1-9])$/.test(lines[i])) {
            const nxt = lines[i+1] || '';
            if (/^[A-Z][A-Z .'\\u2019-]+$/.test(nxt) &&
                !/^(WK|BAT|BWL|AR)$/.test(nxt))
                out[parseInt(lines[i])] = nxt.toUpperCase();
        }
    }
    return out;
}"""

JS_SET_HANDLE = """(h) => {
    try { localStorage.setItem('five-hundred-handle', h);
          if (!localStorage.getItem('five-hundred-pid'))
              localStorage.setItem('five-hundred-pid',
                  Date.now().toString(36) + Math.random().toString(36).slice(2));
          return localStorage.getItem('five-hundred-handle'); } catch(e) { return ''; }
}"""
JS_GET_PID = "() => localStorage.getItem('five-hundred-pid') || ''"

JS_FETCH_BOARD = """async (url) => {
    try { const r = await fetch(url); if (!r.ok) return 'HTTP '+r.status;
          return await r.text(); } catch(e) { return 'ERR '+e; }
}"""

# ---------------- helpers ----------------
async def counter(page):
    try: return await page.evaluate(JS_COUNTER)
    except Exception: return -1

async def read_cards(page):
    try: return await page.evaluate(JS_CARDS)
    except Exception: return []

async def wait_cards(page, timeout=12):
    t0 = time.time()
    while time.time() - t0 < timeout:
        cards = await read_cards(page)
        if len(cards) >= 8:
            return cards
        await asyncio.sleep(0.35)
    return []

async def wait_counter(page, before, timeout=8):
    t0 = time.time()
    while time.time() - t0 < timeout:
        n = await counter(page)
        if n > before:
            return n
        await asyncio.sleep(0.25)
    return -1

async def resolve_pos(page, name, fallback):
    try:
        slots = await page.evaluate(JS_XI_SLOTS)
        up = name.upper()
        for q, nm in slots.items():
            if up.startswith(nm) or nm.startswith(up):
                return int(q)
    except Exception:
        pass
    return fallback

async def press_btn(page, regex, tries=3):
    for _ in range(tries):
        try:
            loc = page.get_by_role("button", name=regex).first
            if await loc.is_visible():
                await loc.click(timeout=2500)
                return True
        except Exception:
            pass
        await asyncio.sleep(0.8)
    return False

async def do_pick(page, c, want_pos):
    before = await counter(page)
    if not await page.evaluate(JS_CLICK_CARD, c['name']):
        return None
    digits, t0 = [], time.time()
    while time.time() - t0 < 5:
        digits = await page.evaluate(JS_POPUP_DIGITS)
        if any(not d['dis'] and d['op'] > 0.85 for d in digits):
            break
        n = await counter(page)
        if n > before:
            pos = await resolve_pos(page, c['name'], want_pos)
            log(f"      auto-placed at {pos}")
            return n, pos
        await asyncio.sleep(0.3)
    usable = [d['n'] for d in digits if not d['dis'] and d['op'] > 0.85]
    if not usable:
        return None
    pos = want_pos if want_pos in usable else usable[0]
    if not await page.evaluate(JS_CLICK_POSITION, pos):
        return None
    n = await wait_counter(page, before, timeout=8)
    if n < 0:
        await page.evaluate(JS_CANCEL_POPUP)
        return None
    real = await resolve_pos(page, c['name'], pos)
    return n, real

# ---------------- strategy (margin-maximizing) ----------------
def typpp_pick_pos(name):
    return TYPPP.get(name, [])

def pick_score(c, q, assigned):
    """marginal avg-margin contribution of placing card c at slot q"""
    wb = c['b'] * W_BAT if q <= 7 else 0
    wp = c['p'] * W_POW if q <= 7 else 0
    wl = c['bl'] * W_BWL if q >= 8 else 0
    return wb + wp + wl

def choose(cards, assigned, spin_no, rerolls):
    free_top = len([q for q in range(1, 8) if q not in assigned])
    have_wk = any(p.get('wk') for p in assigned.values())
    # keeper urgency
    if not have_wk and spin_no >= 7:
        wks = [c for c in cards if c['role'] == 'WK']
        if wks:
            wks.sort(key=lambda c: -(c['b'] + c['p']))
            c = wks[0]
            frees = [q for q in range(c['lo'], min(c['hi'], 11)+1) if q not in assigned]
            if frees: return (c, frees[0])
    # rank every legal placement by projected final margin,
    # but only among placements that keep tier-1 realistically reachable
    cand = []
    for c in cards:
        is_bowler = c['role'] == 'BOWLER'
        if is_bowler and free_top >= 2 and rerolls > 0:
            continue                       # never burn a spin on a pure bowler yet
        tp = typpp_pick_pos(c['name'])
        for q in range(c['lo'], min(c['hi'], 11) + 1):
            if q in assigned: continue
            # glove-first keepers must not eat premium batting slots early
            if (c['role'] == 'WK' and c['b'] < 78 and q <= 7
                    and spin_no < 7):
                continue
            trial = dict(assigned)
            trial[q] = dict(c, wk=(c['role'] == 'WK'))
            if not feasible(trial): continue
            np_ = project_n(trial)
            bonus = 0.0
            if c['role'] == 'WK' and not have_wk: bonus += 0.8
            if tp and q == tp[0]: bonus += 0.15
            elif tp and q in tp:  bonus += 0.08
            cand.append((np_ + bonus, np_, c, q))
    if cand:
        cand.sort(key=lambda x: (-x[0], -x[1]))
        _, _, c, q = cand[0]
        return (c, q)
    # nothing feasible left on this board:
    if free_top > 0 and rerolls > 0:
        return None                       # spend the reroll, don't poison the XI
    # relaxed fallback: best raw value that fits a free slot
    fb_ = []
    for c in cards:
        is_bowler = c['role'] == 'BOWLER'
        if is_bowler and free_top >= 2 and rerolls > 0:
            continue
        for q in range(c['lo'], min(c['hi'], 11) + 1):
            if q in assigned: continue
            fb_.append((pick_score(c, q, assigned), c, q))
    if not fb_:
        return None
    fb_.sort(key=lambda x: -x[0])
    _, c, q = fb_[0]
    return (c, q)

def project_n(assigned, caps=(95, 95, 96)):
    ft = len([q for q in range(1, 8) if q not in assigned])
    fb = len([q for q in range(8, 12) if q not in assigned])
    sb = sum(p['b'] for q, p in assigned.items() if q <= 7) + ft * caps[0]
    sp = sum(p['p'] for q, p in assigned.items() if q <= 7) + ft * caps[1]
    sl = sum(p['bl'] for q, p in assigned.items() if q >= 8) + fb * caps[2]
    return (sb / 7 - 86) + (sp / 7 - 89) + (sl / 4 - 90)

def req_caps(ft):
    """per-remaining-slot fill expectations; tighten as slots run out"""
    if ft >= 3: return (93, 94, 95)
    if ft == 2: return (92, 93, 95)
    return (90, 91, 95)

def feasible(trial):
    """can this partial XI still reach tier-1 with realistic late fills?"""
    ft = len([q for q in range(1, 8) if q not in trial])
    fb = len([q for q in range(8, 12) if q not in trial])
    cb, cp, cl = req_caps(ft)
    sb = sum(p['b'] for q, p in trial.items() if q <= 7)
    sp = sum(p['p'] for q, p in trial.items() if q <= 7)
    sl = sum(p['bl'] for q, p in trial.items() if q >= 8)
    wk = any(p.get('wk') for p in trial.values())
    n70 = sum(1 for p in trial.values() if p['bl'] >= 70)
    free = ft + fb
    if not (wk or free >= 3): return False
    if not (n70 >= 3 or free >= (3 - n70)): return False
    return (sb + ft * cb >= THR_BAT and sp + ft * cp >= THR_POW
            and sl + fb * cl >= THR_BWL)

def dead_end(assigned):
    return not feasible(assigned)

def est_overs(n_margin):
    B = min(max(n_margin, 0) / 16.5, 1)
    balls = max(204, min(300, 282 - 72 * B))
    return round(balls / 6, 1)

# ---------------- one draft ----------------
WIN_KEYS  = ("HISTORY REWRITTEN",)
LOSS_KEYS = ("CHOKED", "HEARTBREAK", "OUTCLASSED", "UNPREPARED",
             "Didn't reach 500", "FINAL SCORE")

async def one_draft(page, idx, handle_info):
    rec = {"draft": idx, "ts": datetime.now().isoformat(),
           "picks": [], "simulated": False}
    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(2.5)
    await page.evaluate(JS_SET_HANDLE, handle_info["handle"])
    await press_btn(page, re.compile("easy", re.I), tries=2)
    await asyncio.sleep(1.0)
    if not await press_btn(page, re.compile("draft", re.I)):
        rec["error"] = "no DRAFT"; return rec
    await asyncio.sleep(1.5)
    await press_btn(page, re.compile("^spin$", re.I))

    assigned, used = {}, set()
    rerolls = 1
    stall = 0
    spin1_checked = False
    while True:
        n = await counter(page)
        if n >= 11:
            break
        spin_no = n + 1
        cards = await wait_cards(page, timeout=2)
        if len([c for c in cards if c['name'] not in used]) < 2:
            deadline, pressed_at = time.time() + 20, 0.0
            ok_board = False
            while time.time() < deadline:
                fresh = await read_cards(page)
                if len([c for c in fresh if c['name'] not in used]) >= 2:
                    cards, ok_board = fresh, True
                    break
                has_rr = await page.get_by_role("button", name=re.compile("re-roll", re.I)).count() > 0
                has_sp = await page.get_by_role("button", name=re.compile("^spin$", re.I)).count() > 0
                if has_sp and not has_rr and time.time() - pressed_at > 4:
                    await press_btn(page, re.compile("^spin$", re.I))
                    pressed_at = time.time()
                await asyncio.sleep(1.0)
            if not ok_board:
                rec["error"] = f"board stuck at {n}"
                return rec

        pool = [c for c in cards if c['name'] not in used]

        # spin-1 gate: squads come from ONE team+era, so a weak first board
        # caps the whole draft -> restart unless a true elite shows up
        if not spin1_checked:
            spin1_checked = True
            elite_bat = any(
                c['role'] != 'BOWLER' and (
                    (c['b'] >= 86 and c['p'] >= 88)
                    or (c['role'] == 'WK' and c['b'] >= 84 and c['p'] >= 88))
                for c in pool)
            ace = any(c['bl'] >= 93 for c in pool)
            if not elite_bat and not ace:
                rec["error"] = "spin1 weak -> instant restart"
                log("  s1: no elite anchor -> restart")
                return rec

        choice = choose(pool, assigned, spin_no, rerolls)
        # reroll policy: no viable pick while batting slots open, reroll banked
        if choice is None and rerolls:
            log(f"  s{spin_no}: no good target -> RE-ROLL")
            if await press_btn(page, re.compile("re-roll", re.I)):
                rerolls -= 1
                await asyncio.sleep(2.5)
                pool = [c for c in await wait_cards(page) if c['name'] not in used]
                choice = choose(pool, assigned, spin_no, rerolls)
        if choice is None:
            if not pool:
                stall += 1
                if stall > 3:
                    rec["error"] = f"dead board at {n}"
                    return rec
                await asyncio.sleep(1.5)
                continue
            pool.sort(key=lambda c: -(c['b'] * W_BAT + c['p'] * W_POW + c['bl'] * W_BWL))
            c0 = pool[0]
            frees = [q for q in range(c0['lo'], min(c0['hi'], 11) + 1) if q not in assigned]
            choice = (c0, frees[0] if frees else None)
        c, want = choice
        if want is None:
            frees = [q for q in range(c['lo'], min(c['hi'], 11) + 1) if q not in assigned]
            want = frees[0] if frees else None
        log(f"  s{spin_no}: {c['name']} ({c['role']} b={c['b']} p={c['p']} bl={c['bl']}) -> {want}")
        res = await do_pick(page, c, want)
        if res is None:
            stall += 1
            log(f"      UNCONFIRMED (stall {stall})")
            if stall > 2:
                rec["error"] = f"unconfirmed pick at {n}"
                return rec
            continue
        stall = 0
        n2, real_q = res
        assigned[real_q] = dict(c, wk=(c['role'] == 'WK'))
        used.add(c['name'])
        rec["picks"].append({"pos": real_q, **{k: c[k] for k in ("name", "role", "b", "p", "bl")}})
        if n2 < 11 and dead_end(assigned):
            log(f"  unsalvageable at {n2}/11 -> abandon")
            rec["error"] = "abandoned (dead end)"
            return rec

    # ---- metrics
    sb = sum(p['b'] for q, p in assigned.items() if q <= 7)
    sp = sum(p['p'] for q, p in assigned.items() if q <= 7)
    sl = sum(p['bl'] for q, p in assigned.items() if q >= 8)
    n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
    has_wk = any(p['wk'] for p in assigned.values())
    n_real = (sb / 7 - 86) + (sp / 7 - 89) + (sl / 4 - 90)
    n_proj = project_n(assigned)
    tier1 = has_wk and n70 >= 3 and sb >= THR_BAT and sp >= THR_POW and sl >= THR_BWL
    rec["metrics"] = {"sum_bat7": sb, "sum_pow7": sp, "sum_bwl4": sl,
                      "n70": n70, "wk": has_wk, "tier1": tier1,
                      "margin_N": round(n_real, 2),
                      "margin_N_proj": round(n_proj, 2),
                      "est_overs_at_min": est_overs(n_real)}
    log(f"  XI: BAT={sb} POW={sp} BWL={sl} n70={n70} wk={has_wk}")
    log(f"  margin N={n_real:.2f} (proj {n_proj:.2f}) est~{est_overs(n_real)}ov "
        f"=> {'TIER-1 -> SIMULATE' if tier1 else 'sub-tier -> skip'}")
    rec["xi"] = [{"pos": q, **{k: p[k] for k in ("name", "b", "p", "bl", "wk")}}
                 for q, p in sorted(assigned.items())]

    if not tier1:
        return rec

    # ---- simulate
    rec["simulated"] = True
    await asyncio.sleep(1.0)
    if not await press_btn(page, re.compile("^simulate$", re.I), tries=2):
        rec["error"] = "SIMULATE not clickable"
        return rec
    await asyncio.sleep(2.5)
    for _ in range(8):
        done = True
        for lbl in ("Skip to end", "Fast"):
            try:
                loc = page.get_by_text(re.compile(lbl, re.I)).first
                if await loc.is_visible():
                    await loc.click(timeout=1500)
                    done = False
                    break
            except Exception:
                pass
        if done:
            break
        await asyncio.sleep(1.2)
    last, stable = "", 0
    for _ in range(45):
        txt = await page.evaluate("() => document.body.innerText")
        if txt == last:
            stable += 1
            if stable >= 4: break
        else:
            stable, last = 0, txt
        await asyncio.sleep(1)
    (LIVE_DIR / f"after_sim_d{idx}.txt").write_text(last or "", encoding="utf-8")

    up = (last or "").upper()
    won = any(k in up for k in WIN_KEYS)
    m = None
    if last:
        lines = last.splitlines()
        for i, L in enumerate(lines):
            if "FINAL SCORE" in L.upper():
                for j in range(i + 1, min(i + 4, len(lines))):
                    mm = re.match(r"\s*(\d{2,3})/(\d{1,2})\s*$", lines[j])
                    if mm: m = mm; break
            if m: break
        ov = re.search(r"(\d{1,2}\.\d)\s*OVERS", last)
        if ov: rec["overs"] = float(ov.group(1))
    if m:
        score, wkts = int(m.group(1)), int(m.group(2))
        rec.update({"score": score, "wkts": wkts,
                    "win": bool(won and score >= 501)})
        ov_s = f" in {rec['overs']} ov" if rec.get("overs") else ""
        log(f"  RESULT: {score}/{wkts}{ov_s}"
            f" {'*** HISTORY REWRITTEN ***' if won else ''}")
    else:
        rec["error"] = "result not parsed"
        rec["win"] = won
        await shot(page, f"d{idx}_unparsed")
    await shot(page, f"d{idx}_end")
    return rec

# ---------------- main ----------------
async def main():
    import os
    max_drafts   = int(os.environ.get("MAX_DRAFTS", "48"))
    stop_on_win  = os.environ.get("STOP_ON_WIN", "1") == "1"
    fast_only    = os.environ.get("FAST_WIN_ONLY", "1") == "1"
    handle_base  = os.environ.get("HANDLE_BASE", "kunjan")
    handle = f"{handle_base}{random.randint(1000, 9999)}"
    handle_info = {"handle": handle}
    stats = {"drafts": 0, "tier1": 0, "sims": 0, "wins": 0, "fast_wins": 0}
    log("=" * 62)
    log(f" BOT v4 | handle={handle} | MAX_DRAFTS={max_drafts} "
        f"| STOP_ON_WIN={stop_on_win} | FAST_WIN_ONLY={fast_only}")
    log("=" * 62)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        ctx = await browser.new_context(viewport={"width": 480, "height": 1000})
        page = await ctx.new_page()
        for idx in range(1, max_drafts + 1):
            stats["drafts"] = idx
            log(f"\n===== DRAFT #{idx} | wins={stats['wins']} "
                f"(fast {stats['fast_wins']}) tier1={stats['tier1']} =====")
            rec = await one_draft(page, idx, handle_info)
            save_run(rec)
            if rec.get("error"):
                log(f"  draft error: {rec['error']}")
            if rec.get("metrics", {}).get("tier1"):
                stats["tier1"] += 1
            if rec.get("simulated"):
                stats["sims"] += 1
                # DRAFT AGAIN is faster than a reload
                await press_btn(page, re.compile("draft again", re.I), tries=2)
            if rec.get("win"):
                stats["wins"] += 1
                ov = rec.get("overs")
                fast = ov is not None and ov < 40
                if fast: stats["fast_wins"] += 1
                log(f"########## 500 CHASED @ {ov} ov | {score_str(rec)} ##########")
                await asyncio.sleep(5)          # let the app's own auto-submit land
                claim = await claim_spot(page, handle)
                rec["claim"] = claim
                if claim["claimed"]:
                    log(f"  CLAIMED spot as {handle} "
                        f"(modal={claim['modal_opened']}, input={claim['input_found']})")
                    await asyncio.sleep(2)
                post = await verify_posted(page, handle, idx)
                rec["posted"] = post
                if post["you"] and post["you"].get("rank") or post["listed"]:
                    log(f"  LEADERBOARD ✔ {handle} | you={post['you']} | ui={post['ui_ranks']}")
                else:
                    log(f"  leaderboard: not confirmed yet (ui={post['ui_ranks']})")
                # close any remaining modal before next draft
                for lbl in ("Done", "Great", "Continue", "Maybe later"):
                    try:
                        b = page.get_by_role("button", name=re.compile(lbl, re.I)).first
                        if await b.count() and await b.is_visible():
                            await b.click(timeout=1500)
                            break
                    except Exception:
                        pass
                if stop_on_win and (not fast_only or fast):
                    log("STOPPING (target met)")
                    break
            await asyncio.sleep(1.5)
        log(f"\nFINAL: {stats}")
        await browser.close()

def score_str(rec):
    if "score" in rec:
        return f"{rec['score']}/{rec['wkts']}"
    return "-"

JS_BOARD_YOU = """() => {
    const t = document.body.innerText || '';
    const out = {};
    let m = t.match(/#(\\d+)\\s*\\n\\s*ALL-TIME/i);   if (m) out.alltime = +m[1];
    m = t.match(/#(\\d+)\\s*\\n\\s*THIS WEEK/i);     if (m) out.week = +m[1];
    m = t.match(/#(\\d+)\\s*\\n\\s*TODAY/i);         if (m) out.today = +m[1];
    return out;
}"""

async def claim_spot(page, handle):
    """open share modal, confirm handle, press CLAIM MY SPOT"""
    clicked = False
    try:
        loc = page.get_by_role("button", name=re.compile("share result", re.I)).first
        if await loc.count() and await loc.is_visible():
            await loc.click(timeout=2500)
            clicked = True
            await asyncio.sleep(1.4)
    except Exception:
        pass
    filled = False
    try:
        inp = page.get_by_placeholder(re.compile("pick a handle", re.I)).first
        if await inp.count() and await inp.is_visible():
            cur = (await inp.input_value() or "").strip()
            if cur != handle:
                await inp.fill(handle)
            filled = True
    except Exception:
        pass
    ok = False
    try:
        btn = page.get_by_role("button", name=re.compile("claim my spot", re.I)).first
        if await btn.count() and await btn.is_visible():
            await btn.click(timeout=3000)
            ok = True
            await asyncio.sleep(4.0)
    except Exception:
        pass
    return {"modal_opened": clicked, "input_found": filled, "claimed": ok}

async def verify_posted(page, handle, idx):
    pid = await page.evaluate(JS_GET_PID)
    board = await page.evaluate(
        JS_FETCH_BOARD,
        "https://500leaderboard.raasnhafiz.workers.dev"
        f"/board?window=2&id={pid}")
    (LIVE_DIR / f"board_after_win_{idx}.json").write_text(board or "", encoding="utf-8")
    you = None
    try:
        you = (json.loads(board) or {}).get("you")
    except Exception:
        pass
    listed = handle.lower() in (board or "").lower()
    ui = await page.evaluate(JS_BOARD_YOU)
    return {"you": you, "listed": listed, "ui_ranks": ui}

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
