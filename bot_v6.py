"""
500/0 BOT v6 - EXACT ENGINE REPLICA
===================================
Reverse-engineered from /assets/app.js function e6():

  score = f(XI):
   - no WK flagged player          -> 210-250  (no_keeper)
   - fewer than 3 players BL>=70   -> 210-250  (too_few_bowlers)
   - avg(BAT of positions 1-7)>=86
     AND avg(POW of positions 1-7)>=89
     AND avg(BWL of positions 8-11)>=90
        -> 70% EXACTLY 500 (WIN) / 30% 496-499 (fell_at_death -> redraft)
   - BAT>=86 & POW>=89, BWL<90     -> 470-495
   - BAT>=85 -> 450-469 | >=84 -> 400-449 | >=83 -> 350-399
   - >=82 -> 300-349 | >=81 -> 200-299 | else 100-199

Strategy:
   slots 1-7 : maximize min(BAT-sum margin, POW-sum margin) toward 602/623,
               prefer WK-flagged elites early
   slots 8-11: maximize BWL sum toward 360 (avg>=90); prefer slot 8 coverage
   spin #1   : if squad has no anchor (elite batter/keeper/bowler) -> reload loop
   RE-ROLL   : saved for first mid-draft spin with no viable candidate

RUN: python bot_v6.py
"""

import asyncio, json, re, sys, pathlib, time
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL      = "https://500-0.com"
HEADLESS = False
BASE     = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v6.json"
SHOT_DIR = BASE / "screenshots_v6"; SHOT_DIR.mkdir(exist_ok=True)

THR_BAT_SUM, THR_POW_SUM, THR_BWL_SUM = 602, 623, 360   # 7*86, 7*89, 4*90

def log(m): print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")

async def shot(page, name):
    try: await page.screenshot(path=str(SHOT_DIR / f"{name}.png"), full_page=True)
    except Exception: pass

# ---------------- DOM READERS ----------------
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

async def click_button_text(page, txt, exact=False):
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

async def click_player_by_name(page, name):
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
    except Exception: return ""

async def wait_for_squad(page, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        squad = await read_squad(page)
        if len(squad) >= 10:
            return squad
        await asyncio.sleep(0.4)
    return []

async def choose_position(page, prefer_order):
    """If position chooser popup is open, click first preferred available number."""
    for _ in range(12):
        nums = await page.evaluate("""() => {
            const found = [];
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim();
                if (/^\\d$/.test(t)) found.push(parseInt(t));
            }
            return found;
        }""")
        if nums:
            for pref in prefer_order:
                if pref in nums:
                    ok = await page.evaluate("""(n) => {
                        for (const b of document.querySelectorAll('button'))
                            if ((b.innerText||'').trim() === String(n)) { b.click(); return true; }
                        return false;
                    }""", pref)
                    if ok: return pref
            return None
        await asyncio.sleep(0.35)
    return None

# ---------------- STRATEGY ----------------
def pick_for_slot(squad, taken_names, assigned):
    free = [q for q in range(1, 12) if q not in assigned]
    top_free = [q for q in free if q <= 7]
    bwl_free = [q for q in free if q >= 8]

    cur_bat = sum(p['b'] for q, p in assigned.items() if q <= 7)
    cur_pow = sum(p['p'] for q, p in assigned.items() if q <= 7)
    cur_bwl = sum(p['bl'] for q, p in assigned.items() if q >= 8)
    have_wk = any(p.get('wk') for p in assigned.values())

    best, best_key = None, None
    for c in squad:
        if c['name'] in taken_names or not c.get('enabled'): continue
        is_wk = 'WK' in (c.get('role') or '')
        for q in range(c['lo'], c['hi'] + 1):
            if q not in free: continue
            if q <= 7:
                nb, np_, nl = cur_bat + c['b'], cur_pow + c['p'], cur_bwl
                rem_t, rem_b = len(top_free) - 1, len(bwl_free)
            else:
                nb, np_, nl = cur_bat, cur_pow, cur_bwl + c['bl']
                rem_t, rem_b = len(top_free), len(bwl_free) - 1
            opt_bat = nb + (97 * rem_t if rem_t > 0 else 0)
            opt_pow = np_ + (98 * rem_t if rem_t > 0 else 0)
            opt_bwl = nl + (96 * rem_b if rem_b > 0 else 0)
            if opt_bat < THR_BAT_SUM or opt_pow < THR_POW_SUM or opt_bwl < THR_BWL_SUM:
                continue
            wk_ok = have_wk or is_wk or rem_t + rem_b > 0
            if not wk_ok:
                continue
            div_t = max(1, rem_t + (1 if q <= 7 else 0))
            div_b = max(1, rem_b + (1 if q >= 8 else 0))
            mb = (opt_bat - THR_BAT_SUM) / div_t
            mp = (opt_pow - THR_POW_SUM) / div_t
            ml = (opt_bwl - THR_BWL_SUM) / div_b
            key = (min(mb, mp, ml), mb + mp + ml)
            if best_key is None or key > best_key:
                best_key, best = key, (c, q)
    return best

def squad_has_anchor(squad):
    for c in squad:
        if c['b'] + c['p'] >= 178 and c['lo'] <= 7: return True
        if c['bl'] >= 93: return True
    return False

# ---------------- RESULT ----------------
FAIL_KEYS = ("FELL SHORT", "HEARTBREAK", "ALL OUT", "FELL AT", "SO CLOSE",
             "DENIED", "AGONY", "SHORT.", "FELL", "CRUEL")

async def wait_result(page, timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        txt = await body_text(page)
        up = txt.upper()
        stripped = txt.replace("500/0", "")
        if "500 CLUB" in up or "YOU DID IT" in up or "CHASED" in up:
            return parse_score(stripped, win=True)
        if any(k in up for k in FAIL_KEYS):
            return parse_score(stripped, win=False)
        m2 = re.search(r"(\d{3,4})\s*/\s*(\d)", stripped)
        if m2 and ("OVER" in up or "BALL" in up or "SHORT" in up):
            sc = int(m2.group(1))
            return parse_score(stripped, win=sc >= 500)
        await asyncio.sleep(1.0)
    return {"score": None, "win": False, "timeout": True}

def parse_score(stripped, win):
    m = re.search(r"(\d{3,4})\s*/\s*(\d)", stripped)
    ov = re.search(r"(\d{2,3}\.\d)\s*OVER", stripped.upper())
    return {"score": int(m.group(1)) if m else (500 if win else None),
            "wkts": int(m.group(2)) if m else None,
            "overs": ov.group(1) if ov else None,
            "win": win}

# ---------------- ONE DRAFT SESSION ----------------
async def draft_session(pw, sid):
    rec = {"session": sid, "ts": datetime.now().isoformat(), "reloads": 0,
           "reroll_used": False, "drafted": [], "success": False}
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(viewport={"width": 480, "height": 1000})
    page = await ctx.new_page()
    try:
        # ---- phase 1: gated start — reload until spin#1 squad has an anchor
        anchored = False
        for attempt in range(40):
            await page.goto(URL, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2.5)
            await click_button_text(page, "EASY")
            await asyncio.sleep(0.4)
            await click_button_text(page, "DRAFT")
            await asyncio.sleep(2.0)
            ok = await click_button_text(page, "SPIN", exact=True)
            if not ok:
                await asyncio.sleep(1.5)
                ok = await click_button_text(page, "SPIN", exact=True)
                if not ok: continue
            squad = await wait_for_squad(page)
            if not squad:
                rec["reloads"] += 1
                continue
            names = [c['name'] for c in squad]
            log(f"  spin#1: {names[:4]} ... b+p max={max(c['b']+c['p'] for c in squad)}")
            if squad_has_anchor(squad):
                anchored = True
                log(f"  ANCHOR FOUND after {rec['reloads']} reload(s)")
                break
            rec["reloads"] += 1
        if not anchored:
            log("  no anchor after 40 reloads - proceeding anyway")
        await shot(page, f"s{sid}_spin1_locked")

        # ---- phase 2: fill 11 slots
        assigned, taken = {}, set()
        rerolls_left = 1
        stall = 0
        while len(assigned) < 11:
            slot_num = len(assigned) + 1
            squad = await read_squad(page)
            if len(squad) < 10:
                ok = await click_button_text(page, "SPIN", exact=True)
                if not ok:
                    await asyncio.sleep(1.2)
                    await click_button_text(page, "SPIN", exact=True)
                squad = await wait_for_squad(page)

            choice = pick_for_slot(squad, taken, assigned)

            if choice is None and rerolls_left > 0:
                log(f"  slot{slot_num}: no viable candidate -> RE-ROLL")
                if await click_button_text(page, "RE-ROLL"):
                    rerolls_left -= 1
                    rec["reroll_used"] = True
                    await asyncio.sleep(2.8)
                    squad = await wait_for_squad(page)
                    choice = pick_for_slot(squad, taken, assigned)

            if choice is None:
                # forced pick: best enabled card by role-appropriate rating
                cand = [c for c in squad if c['name'] not in taken and c.get('enabled')]
                if not cand:
                    stall += 1
                    if stall > 3:
                        log("  dead end - restarting session")
                        return None
                    await asyncio.sleep(2)
                    continue
                free = [q for q in range(1, 12) if q not in assigned]
                need_bwl = len([q for q in free if q >= 8]) > 0
                def val(c):
                    qs = [q for q in free if c['lo'] <= q <= c['hi']]
                    return ((-c['bl'] if need_bwl else -(c['b'] + c['p'])), min(qs) if qs else 99)
                cand.sort(key=val)
                best_c = cand[0]
                qs = [q for q in free if best_c['lo'] <= q <= best_c['hi']]
                choice = (best_c, qs[0] if qs else free[0])
                log(f"  slot{slot_num}: FORCED pick {choice[0]['name']}")

            c, q = choice
            log(f"  slot{slot_num}: pick {c['name']} at pos {q} "
                f"[b={c['b']} p={c['p']} bl={c['bl']}]")
            clicked = await click_player_by_name(page, c['name'])
            if not clicked:
                log("    click failed - retrying once")
                await asyncio.sleep(1)
                clicked = await click_player_by_name(page, c['name'])
                if not clicked:
                    stall += 1
                    if stall > 3: return None
                    continue
            pos = await choose_position(page, [q] + [x for x in range(1, 12) if x != q])
            if pos is not None and pos != q:
                log(f"    popup gave pos {pos} instead of {q}")
                q = pos
            await asyncio.sleep(0.8)
            assigned[q] = dict(c, wk=('WK' in (c.get('role') or '')))
            taken.add(c['name'])
            stall = 0
            rec["drafted"].append({"pos": q, "name": c['name'], "b": c['b'],
                                   "p": c['p'], "bl": c['bl'], "role": c['role']})
            await shot(page, f"s{sid}_slot{len(assigned):02d}")

        # ---- phase 3: simulate + read REAL result
        bat7 = [assigned[q] for q in sorted(assigned) if q <= 7]
        bwl4 = [assigned[q] for q in sorted(assigned) if q >= 8]
        abat = sum(p['b'] for p in bat7) / 7
        apow = sum(p['p'] for p in bat7) / 7
        abwl = sum(p['bl'] for p in bwl4) / 4
        n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
        has_wk = any(p['wk'] for p in assigned.values())
        will_win_tier = (has_wk and n70 >= 3 and abat >= 86 and apow >= 89 and abwl >= 90)
        rec["metrics"] = {"avg_bat_top7": round(abat, 2), "avg_pow_top7": round(apow, 2),
                          "avg_bwl_8_11": round(abwl, 2), "n_bwl_ge70": n70,
                          "has_wk": has_wk, "hits_all_thresholds": will_win_tier}
        log(f"  XI metrics: BAT={abat:.1f} POW={apow:.1f} BWL={abwl:.1f} "
            f"n70={n70} wk={has_wk} => {'TIER-1 (70% win)' if will_win_tier else 'sub-tier'}")

        await asyncio.sleep(1.5)
        ok = await click_button_text(page, "SIMULATE", exact=True)
        if not ok:
            ok = await click_button_text(page, "SIMULATE")
        log("  SIMULATE clicked")
        res = await wait_result(page)
        rec.update(res)
        rec["success"] = bool(res.get("win"))
        await shot(page, f"s{sid}_result")
        emoji = "500 CLUB!" if res.get("win") else f"{res.get('score')}"
        log(f"  RESULT: {emoji} ({res})")
    except Exception as e:
        import traceback; traceback.print_exc()
        rec["error"] = str(e)
    finally:
        try: await browser.close()
        except Exception: pass
    return rec

# ---------------- MAIN LOOP ----------------
async def main():
    import os
    max_drafts = int(os.environ.get("MAX_DRAFTS", "0")) or None
    stop_on_win = os.environ.get("STOP_ON_WIN", "1") == "1"
    total = wins = tier1 = 0
    log("=" * 62)
    log("  BOT v6 - exact engine replica - threshold strategy")
    log("=" * 62)
    async with async_playwright() as pw:
        while max_drafts is None or total < max_drafts:
            total += 1
            log(f"\n===== DRAFT #{total} | wins so far: {wins} =====")
            rec = None
            for retry in range(3):
                rec = await draft_session(pw, total)
                if rec is not None:
                    break
                log("  session aborted - retrying")
            if rec is None:
                continue
            save_run(rec)
            if rec.get("metrics", {}).get("hits_all_thresholds"):
                tier1 += 1
            if rec.get("success"):
                wins += 1
                log(f"########## WIN #{wins} - SCORE {rec.get('score')} ##########")
                if stop_on_win:
                    log("STOP_ON_WIN set -> exiting loop")
                    break
            await asyncio.sleep(2)
    log(f"FINAL: {wins} wins / {total} drafts | tier-1 teams: {tier1}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped by user")

