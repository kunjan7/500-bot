"""
500/0 BOT v2 - CONFIRMED PICKS (card -> position popup -> counter)
==================================================================
Mechanics learned from live DOM:
  * Flow: HOME -> EASY -> DRAFT -> SPIN -> squad of ~13 cards
  * Clicking a card opens "Choose a batting position" popup:
      buttons '1'..'11' (legal slots only) + 'cancel'
  * Counter N/11 increments ONLY after a position button is pressed.
    Single-position players may auto-place (no popup).
  * Card text embeds stats: "NAME ROLE lo-hi BAT POW BWL"
      e.g. 'Babar Azam BATTER1-390BAT84POW6BWL' -> range 1-3 b=90 p=84 bl=6

Win tier (engine): WK present, >=3 players BL>=70,
  sum BAT(pos1-7)>=602, sum POW(pos1-7)>=623, sum BWL(pos8-11)>=360.

RUN: python bot_v2.py
"""

import asyncio, json, re, sys, time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL      = "https://500-0.com"
BASE     = Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v2.json"
SHOT_DIR = BASE / "shots_v2"; SHOT_DIR.mkdir(exist_ok=True)
LIVE_DIR = BASE / "live"
HEADLESS = False

THR_BAT, THR_POW, THR_BWL = 602, 623, 360

CARD_RE = re.compile(
    r"^(?P<name>.+?)\s*(?P<role>BATTER|BOWLER|ALL-ROUNDER|WK)\s*"
    r"(?P<lo>\d+)[-\u2013](?P<hi>\d+)\s*(?P<b>\d+)BAT\s*(?P<p>\d+)POW\s*(?P<bl>\d+)BWL",
    re.I)

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
        // text layout: NAME / ROLE / lo-hi / <v> BAT / <v> POW / <v> BWL
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
            // first line that isn't a known token
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

JS_XI_SLOTS = """() => {
    // map filled slots: strict adjacency of slot-number line -> NAME line
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
                !/^(WK|BAT|BWL|AR)$/.test(nxt)) {
                out[parseInt(lines[i])] = nxt.toUpperCase();
            }
        }
    }
    return out;
}"""

JS_POPUP_DIGITS = """() => {
    const dlg = [...document.querySelectorAll('div')].find(d => {
        const t = d.textContent || '';
        return d.className && String(d.className).includes('fixed') &&
               /Choose a batting position/i.test(t) && d.querySelector('button');
    });
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
    for (const root of roots) {
        for (const b of root.querySelectorAll('button')) {
            if ((b.textContent||'').trim() === String(n) && !b.disabled) {
                b.click(); return true;
            }
        }
    }
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
        if (t.toUpperCase().startsWith(want) && !b.disabled)
            { b.click(); return true; }
    }
    return false;
}"""

# ------------- helpers -------------
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

async def do_pick(page, c, want_pos):
    """Click card, choose position in popup (or auto-place), confirm counter.
       Returns (new_counter, real_pos) or None."""
    before = await counter(page)
    sent = await page.evaluate(JS_CLICK_CARD, c['name'])
    if not sent:
        log(f"      click failed outright")
        return None
    digits = []
    t0 = time.time()
    while time.time() - t0 < 5:
        digits = await page.evaluate(JS_POPUP_DIGITS)
        usable = [d for d in digits if not d['dis'] and d['op'] > 0.85]
        if usable:
            break
        n = await counter(page)
        if n > before:
            log(f"      auto-placed (no popup)")
            pos = await resolve_pos(page, c['name'], want_pos)
            return n, pos
        await asyncio.sleep(0.3)
    if not digits:
        log(f"      no popup appeared")
        return None
    usable = [d['n'] for d in digits if not d['dis'] and d['op'] > 0.85]
    log(f"      popup slots={usable}")
    pos = None
    if want_pos in usable:
        pos = want_pos
    elif usable:
        pos = usable[0]
    if pos is None:
        await page.evaluate(JS_CANCEL_POPUP)
        return None
    ok = await page.evaluate(JS_CLICK_POSITION, pos)
    if not ok:
        log(f"      position click failed")
        return None
    n = await wait_counter(page, before, timeout=8)
    if n < 0:
        log(f"      counter did not advance after choosing {pos}")
        await page.evaluate(JS_CANCEL_POPUP)
        return None
    real = await resolve_pos(page, c['name'], pos)
    log(f"      placed at {real} -> {n}/11")
    return n, real

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

# ------------- strategy (light) -------------
def _choose_pass(cards, assigned, defer_bowlers):
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
        for q in range(c['lo'], c['hi'] + 1):
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

def choose(cards, assigned):
    """Defer pure bowlers while >=3 batting slots are still open (batting
    elites are the scarce resource; bowlers show up everywhere)."""
    free_top = len([q for q in range(1, 8) if q not in assigned])
    non_bowler = _choose_pass(cards, assigned, defer_bowlers=True) if free_top >= 3 else None
    if non_bowler:
        return non_bowler
    return _choose_pass(cards, assigned, defer_bowlers=False)

# ------------- main -------------
async def main():
    rec = {"ts": datetime.now().isoformat(), "picks": [], "errors": []}
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS)
        page = await (await browser.new_context(
            viewport={"width": 480, "height": 1000})).new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(3)

        async def press(regex, exact_label=None, tries=3):
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

        await press(re.compile("^easy$", re.I));           log("EASY ok")
        await asyncio.sleep(1.2)
        await press(re.compile("^draft$", re.I));          log("DRAFT ok")
        await asyncio.sleep(1.5)
        if not await press(re.compile("^spin$", re.I)):
            rec["errors"].append("no initial SPIN")
        log("SPIN ok")
        await shot(page, "01_first_squad")

        assigned, used = {}, set()
        reroll_left = 1
        while True:
            n = await counter(page)
            if n >= 11:
                break
            cards = await wait_cards(page, timeout=2)
            if len([c for c in cards if c['name'] not in used]) < 2:
                # patient provisioning: squads may auto-deal; only press SPIN
                # when the board is truly idle (no RE-ROLL visible)
                deadline = time.time() + 20
                pressed_at = 0.0
                while time.time() < deadline:
                    fresh = await read_cards(page)
                    if len([c for c in fresh if c['name'] not in used]) >= 2:
                        cards = fresh
                        break
                    has_reroll = await page.get_by_role("button", name=re.compile("re-roll", re.I)).count() > 0
                    has_spin = await page.get_by_role("button", name=re.compile("^spin$", re.I)).count() > 0
                    if has_spin and not has_reroll and time.time() - pressed_at > 4:
                        await press(re.compile("^spin$", re.I))
                        pressed_at = time.time()
                    await asyncio.sleep(1.2)
                if len([c for c in cards if c['name'] not in used]) < 2:
                    rec["errors"].append(f"n={n}: no candidates and no SPIN possible")
                    await shot(page, f"fail_nospin_{n+1}")
                    break
            choice = choose([c for c in cards if c['name'] not in used], assigned)
            if choice is None and reroll_left:
                log(f"  n={n}: weak board -> RE-ROLL")
                await press(re.compile("re-roll", re.I))
                reroll_left -= 1
                await asyncio.sleep(2.5)
                cards = await wait_cards(page)
                choice = choose([c for c in cards if c['name'] not in used], assigned)
            if choice is None:
                cand = [c for c in cards if c['name'] not in used]
                if not cand:
                    rec["errors"].append(f"n={n}: dead board, no candidates")
                    await shot(page, f"fail_dead_{n+1}")
                    break
                cand.sort(key=lambda c: -(c['b'] + c['p'] + c['bl']))
                choice = (cand[0], None)
            c, want = choice
            if want is None:
                free = [q for q in range(c['lo'], min(c['hi'], 11) + 1) if q not in assigned]
                want = free[0] if free else None
            log(f"  n={n}: pick {c['name']} ({c['role']} b={c['b']} p={c['p']} bl={c['bl']}) want={want}")
            res = await do_pick(page, c, want)
            if isinstance(res, tuple):
                n, real_q = res
                assigned[real_q] = dict(c, wk=(c['role'] == 'WK'))
                used.add(c['name'])
                rec["picks"].append({"pos": real_q, **{k: c[k] for k in ("name","role","b","p","bl")}})
            else:
                rec["errors"].append(f"n={n}: unconfirmed pick {c['name']}")
                await shot(page, f"fail_pick_{n+1}")
                break

        n = await counter(page)
        log(f"DRAFT COMPLETE: {n}/11  errors={rec['errors']}")
        btns = await page.evaluate("""() => [...document.querySelectorAll('button')]
            .map(b => (b.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30))""")
        log(f"buttons now: {[b for b in btns if b][:15]}")
        txt = await page.evaluate("() => document.body.innerText")
        (LIVE_DIR / "endstate.txt").write_text(txt, encoding="utf-8")
        await shot(page, "98_draft_end")

        if n >= 11:
            for label in ("Simulate", "Play", "Start", "GO"):
                if await press(re.compile(label, re.I), tries=2):
                    log(f"pressed {label}")
                    break
            await asyncio.sleep(3)
            # fast-forward the animation
            for _ in range(6):
                clicked = False
                for lbl in ("Skip to end", "Fast"):
                    try:
                        loc = page.get_by_text(re.compile(lbl, re.I)).first
                        if await loc.is_visible():
                            await loc.click(timeout=1500)
                            clicked = True
                            break
                    except Exception:
                        pass
                if not clicked:
                    break
                await asyncio.sleep(1.5)
            # wait for the screen to settle
            last = ""
            stable = 0
            for _ in range(40):
                txt2 = await page.evaluate("() => document.body.innerText")
                if txt2 == last:
                    stable += 1
                    if stable >= 4:
                        break
                else:
                    stable, last = 0, txt2
                await asyncio.sleep(1)
            (LIVE_DIR / "after_sim.txt").write_text(last or "", encoding="utf-8")
            await shot(page, "99_after_sim")
            m = re.search(r"\b(\d{2,3})\s*/\s*(\d)\b", last or "")
            log(f"FINAL SCORE PARSE: {m.group(0) if m else 'none'}")

        save_run(rec)
        await browser.close()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped")
