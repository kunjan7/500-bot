"""
500/0 BOT v3 - FULL GRINDER (proven mechanics + engine strategy)
================================================================
Per-run flow:
  HOME -> EASY -> DRAFT -> [SPIN -> pick -> position] x11
  -> if XI hits TIER-1 (WK, n70>=3, sumBAT>=602, sumPOW>=623, sumBWL>=360)
        -> SIMULATE -> SKIP TO END -> parse score (win = >=500; engine:
           tier-1 gives exactly 500 @70%, 496-499 @30%)
     else -> skip sim, restart (saves ~25s per doomed draft)

Mechanics (validated live):
  * card click opens position popup ('1'..'11' + cancel); counter N/11
    increments only after choosing; single-option players auto-place
  * squads auto-deal after placement; never press SPIN while RE-ROLL visible
  * result screen: '<score>/<wkts>' + 'N.N OVERS'; DRAFT AGAIN loops fast

RUN: python bot_v3.py            STOP_ON_WIN=0 keeps grinding
"""

import asyncio, json, re, sys, time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL      = "https://500-0.com"
BASE     = Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v3.json"
SHOT_DIR = BASE / "shots_v3"; SHOT_DIR.mkdir(exist_ok=True)
LIVE_DIR = BASE / "live"
HEADLESS = False

THR_BAT, THR_POW, THR_BWL = 602, 623, 360

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

# ---------------- pick ----------------
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

# ---------------- strategy ----------------
def _pass(cards, assigned, defer_bowlers, want_wk_only=False):
    free_top = [q for q in range(1, 8) if q not in assigned]
    free_bot = [q for q in range(8, 12) if q not in assigned]
    bat = sum(p['b'] for q, p in assigned.items() if q <= 7)
    pow_ = sum(p['p'] for q, p in assigned.items() if q <= 7)
    bwl = sum(p['bl'] for q, p in assigned.items() if q >= 8)
    have_wk = any(p.get('wk') for p in assigned.values())
    best, best_key = None, None
    for c in cards:
        if defer_bowlers and c['role'] == 'BOWLER':
            continue
        wk = c['role'] == 'WK'
        if want_wk_only and not wk:
            continue
        for q in range(c['lo'], min(c['hi'], 11) + 1):
            if q in assigned: continue
            kt = len(free_top) - (1 if q <= 7 else 0)
            kb = len(free_bot) - (1 if q >= 8 else 0)
            tb = bat + (c['b'] if q <= 7 else 0) + kt * 88
            tp = pow_ + (c['p'] if q <= 7 else 0) + kt * 89
            tl = bwl + (c['bl'] if q >= 8 else 0) + kb * 91
            if tb < THR_BAT or tp < THR_POW or tl < THR_BWL: continue
            if not (have_wk or wk or (len(free_top) + len(free_bot) - 1) >= 3): continue
            mb = (tb - THR_BAT) / max(1, kt + (1 if q <= 7 else 0))
            mp = (tp - THR_POW) / max(1, kt + (1 if q <= 7 else 0))
            ml = (tl - THR_BWL) / max(1, kb + (1 if q >= 8 else 0))
            bonus = 2.5 if (wk and not have_wk) else 0
            key = (min(mb, mp, ml) + bonus, mb + mp + ml)
            if best_key is None or key > best_key:
                best_key, best = key, (c, q)
    return best

def choose(cards, assigned, spin_no, rerolls=0):
    free_top = len([q for q in range(1, 8) if q not in assigned])
    have_wk = any(p.get('wk') for p in assigned.values())
    # keeper urgency: force a WK pick by spin 8
    if not have_wk and spin_no >= 8:
        w = _pass(cards, assigned, defer_bowlers=False, want_wk_only=True)
        if w: return w
    # never burn a spin on a pure bowler while batting slots remain
    # and the reroll is still in the bank
    if free_top >= 2 and rerolls > 0:
        nb = _pass(cards, assigned, defer_bowlers=True)
        return nb  # None => caller rerolls
    if free_top >= 3:
        nb = _pass(cards, assigned, defer_bowlers=True)
        if nb: return nb
    return _pass(cards, assigned, defer_bowlers=False)

def dead_end(assigned):
    ft = len([q for q in range(1, 8) if q not in assigned])
    fb = len([q for q in range(8, 12) if q not in assigned])
    bat = sum(p['b'] for q, p in assigned.items() if q <= 7)
    pow_ = sum(p['p'] for q, p in assigned.items() if q <= 7)
    bwl = sum(p['bl'] for q, p in assigned.items() if q >= 8)
    wk = any(p.get('wk') for p in assigned.values())
    n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
    free = ft + fb
    wk_ok = wk or free >= 3
    n70_ok = n70 >= 3 or free >= (3 - n70)
    return not (bat + ft * 93 >= THR_BAT and pow_ + ft * 93 >= THR_POW
                and bwl + fb * 94 >= THR_BWL and wk_ok and n70_ok)

# ---------------- one draft ----------------
async def one_draft(page, idx, rec_out):
    rec = {"draft": idx, "ts": datetime.now().isoformat(),
           "picks": [], "simulated": False}
    # fresh game
    await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    await asyncio.sleep(2.5)
    # mode toggle label is 'EASY Ratings shown' -> loose match, never fatal
    await press_btn(page, re.compile("easy", re.I), tries=2)
    await asyncio.sleep(1.0)
    if not await press_btn(page, re.compile("draft", re.I)):
        rec["error"] = "no DRAFT"; return rec
    await asyncio.sleep(1.5)
    await press_btn(page, re.compile("^spin$", re.I))

    assigned, used = {}, set()
    rerolls = 1
    stall = 0
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
        choice = choose(pool, assigned, spin_no, rerolls)
        # early reroll: weak batting board while top slots open
        if (choice is not None and rerolls and spin_no <= 5
                and len([q for q in range(1, 8) if q not in assigned]) >= 3):
            strong = any(c['role'] != 'BOWLER' and c['b'] + c['p'] >= 172 for c in pool)
            if not strong:
                log(f"  s{spin_no}: weak board -> RE-ROLL")
                if await press_btn(page, re.compile("re-roll", re.I)):
                    rerolls -= 1
                    await asyncio.sleep(2.5)
                    pool = await wait_cards(page)
                    choice = choose([c for c in pool if c['name'] not in used],
                                    assigned, spin_no, rerolls)
        if choice is None and rerolls:
            log(f"  s{spin_no}: no batting option worth a spin -> RE-ROLL")
            if await press_btn(page, re.compile("re-roll", re.I)):
                rerolls -= 1
                await asyncio.sleep(2.5)
                pool = await wait_cards(page)
                choice = choose([c for c in pool if c['name'] not in used],
                                assigned, spin_no, rerolls)
        if choice is None:
            if not pool:
                stall += 1
                if stall > 3:
                    rec["error"] = f"dead board at {n}"
                    return rec
                await asyncio.sleep(1.5)
                continue
            pool.sort(key=lambda c: -(c['b'] + c['p'] + c['bl']))
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
            log(f"  optimistically dead at {n2}/11 -> abandon")
            rec["error"] = "abandoned (dead end)"
            return rec

    # ---- metrics
    bat7 = [assigned[q] for q in sorted(assigned) if q <= 7]
    bwl4 = [assigned[q] for q in sorted(assigned) if q >= 8]
    sb = sum(p['b'] for p in bat7); sp = sum(p['p'] for p in bat7); sl = sum(p['bl'] for p in bwl4)
    n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
    has_wk = any(p['wk'] for p in assigned.values())
    tier1 = has_wk and n70 >= 3 and sb >= THR_BAT and sp >= THR_POW and sl >= THR_BWL
    rec["metrics"] = {"sum_bat7": sb, "sum_pow7": sp, "sum_bwl4": sl,
                      "n70": n70, "wk": has_wk, "tier1": tier1}
    log(f"  XI: BAT={sb} POW={sp} BWL={sl} n70={n70} wk={has_wk} "
        f"=> {'TIER-1 -> simulate' if tier1 else 'sub-tier -> skip'}")
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
    m = None
    if last:
        lines = last.splitlines()
        for i, L in enumerate(lines):
            if "FINAL SCORE" in L.upper():
                for j in range(i + 1, min(i + 4, len(lines))):
                    mm = re.match(r"\s*(\d{2,3})/(\d{1,2})\s*$", lines[j])
                    if mm:
                        m = mm
                        break
            if m: break
    if m is None and last:
        m = re.search(r"\n\s*(\d{2,3})/(\d{1,2})\s*\n\s*\d{1,3}\.\d\s*OVERS?\s*\n", last)
    if m:
        score, wkts = int(m.group(1)), int(m.group(2))
        rec.update({"score": score, "wkts": wkts, "win": score >= 500})
        log(f"  RESULT: {score}/{wkts} {'*** WIN ***' if score >= 500 else ''}")
    else:
        rec["error"] = "result not parsed"
        await shot(page, f"d{idx}_result_unparsed")
    return rec

# ---------------- main ----------------
async def main():
    import os
    max_drafts = int(os.environ.get("MAX_DRAFTS", "0")) or None
    stop_on_win = os.environ.get("STOP_ON_WIN", "1") == "1"
    total = sims = wins = tier1 = skipped = 0
    log("=" * 60)
    log(" BOT v3 - grind tier-1 drafts; simulate only qualifying XIs")
    log("=" * 60)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page = await (await browser.new_context(
            viewport={"width": 480, "height": 1000})).new_page()
        while max_drafts is None or total < max_drafts:
            total += 1
            log(f"\n===== DRAFT #{total} | sims={sims} wins={wins} =====")
            rec = await one_draft(page, total, None)
            save_run(rec)
            if rec.get("error"):
                log(f"  draft error: {rec['error']}")
            if rec.get("metrics", {}).get("tier1"):
                tier1 += 1
            if rec.get("simulated"):
                sims += 1
            if rec.get("win"):
                wins += 1
                log(f"########## 500 CHASED! score={rec['score']} ##########")
                if stop_on_win:
                    break
            elif rec.get("simulated") and not rec.get("win"):
                # fell_at_death (496-499) or wrong parse -> loop again via DRAFT AGAIN
                await press_btn(page, re.compile("draft again", re.I), tries=2)
            await asyncio.sleep(1.5)
        log(f"FINAL: {wins} wins | {tier1} tier-1 drafts | {sims} sims | {total} drafts")
        await browser.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
