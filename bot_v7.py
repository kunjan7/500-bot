"""
500/0 BOT v7.2 - PAGE-GROUND-TRUTH + DIFF-BASED RESULT DETECTION
================================================================
Engine (reverse-engineered, unchanged):
  WIN tier needs:  WK-flagged player in XI
                   >=3 players with BWL>=70
                   avg BAT(pos1-7) >= 86   -> sum >= 602
                   avg POW(pos1-7) >= 89   -> sum >= 623
                   avg BWL(pos8-11)>= 90   -> sum >= 360
                   -> 70% exactly 500 / 30% 496-499 (redraft on fail)

v7.1 post-mortem (false positive):
  - Picks at slots 10/11 silently failed -> real state 9/11, internal
    dict claimed 11. Button stayed "SPIN"; "SIMULATE clicked: False".
  - Win detector matched the SITE TITLE "500/0" / nav "500 Legends"
    already present before sim -> instant fake "500 CLUB!".

v7.2 changes:
  1. Ground truth from page: parse "N/11" counter + numbered XI list;
     adopt the REAL slot the game assigned; retry/abort on mismatch.
  2. Simulation only attempted at true 11/11; tries SIMULATE/START/PLAY,
     falls back to SPIN.
  3. Result detection uses ONLY text lines NEW vs pre-sim snapshot
     (site title/nav can never trigger again).
  4. Honest-margin strategy retained (FILL 88/89/91, OPT 93/93/94),
     batting-elite anchor gate, early reroll, WK urgency, strict abort.

RUN:  MAX_DRAFTS=1 python bot_v7.py      STRICT_ABORT=0 allows sub-tier completion
"""

import asyncio, json, re, sys, pathlib, time
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

URL      = "https://500-0.com"
HEADLESS = False
BASE     = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot")
LOG_FILE = BASE / "run_log_v7.json"
SHOT_DIR = BASE / "screenshots_v7"; SHOT_DIR.mkdir(exist_ok=True)
LIVE_DIR = BASE / "live"

THR_BAT, THR_POW, THR_BWL = 602, 623, 360
FILL_B, FILL_P, FILL_BL   = 88, 89, 91
OPT_B, OPT_P, OPT_BL      = 93, 93, 94
WK_URGENT_SPIN            = 8
EARLY_REROLL_MIN_BP       = 172
STRICT_ABORT              = True

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

async def dump_text(page, path_name):
    try:
        txt = await body_text(page)
        (LIVE_DIR / path_name).write_text(txt, encoding="utf-8")
    except Exception:
        pass

NAME_RE = re.compile(r"^[A-Z][A-Z .'\u2019\-]+$")
SKIP_NAMES = {"WK", "BAT", "BWL", "AR", "THE DRAFT", "ALL ROUNDER", "WICKETKEEPER"}

async def draft_truth(page):
    """Ground truth: (filled_count, {slot:int -> NAME-upper}).
    Parses the numbered XI list under 'THE DRAFT'."""
    txt = await body_text(page)
    low = txt.split("Fill all 11 positions.", 1)
    seg = low[1] if len(low) > 1 else txt
    for stop in ("RE-ROLL", "SPIN"):
        seg = seg.split(stop, 1)[0]
    lines = [l.strip() for l in seg.splitlines()]
    pos_map = {}
    for i in range(len(lines) - 1):
        # slot number must be IMMEDIATELY followed by its occupant's name
        if re.fullmatch(r"(10|11|[1-9])", lines[i]) and NAME_RE.fullmatch(lines[i + 1]) \
                and lines[i + 1] not in SKIP_NAMES:
            pos_map[int(lines[i])] = lines[i + 1]
    m = re.search(r"(\d{1,2})\s*/\s*11", txt)
    cnt = int(m.group(1)) if m else len(pos_map)
    return cnt, pos_map

async def wait_for_squad(page, timeout=15):
    t0 = time.time()
    while time.time() - t0 < timeout:
        squad = await read_squad(page)
        if len(squad) >= 10:
            return squad
        await asyncio.sleep(0.4)
    return []

async def choose_position(page, prefer_order, dbg=None):
    """If position chooser popup is open, click first preferred AVAILABLE number."""
    seen_log = []
    chosen = None
    for _ in range(14):
        btns = await page.evaluate("""() => {
            const out = [];
            for (const b of document.querySelectorAll('button')) {
                const t = (b.innerText||'').trim();
                if (!/^\\d$/.test(t)) continue;
                const style = b.getAttribute('style')||'';
                const m = style.match(/opacity:\\s*([\\d.]+)/);
                out.push({n: parseInt(t), dis: !!b.disabled,
                          op: m ? parseFloat(m[1]) : 1});
            }
            return out;
        }""")
        if dbg is not None:
            seen_log.append(btns)
        usable = [x for x in btns if not x['dis'] and x['op'] > 0.85]
        if btns:
            for pref in prefer_order:
                if any(x['n'] == pref for x in usable):
                    ok = await page.evaluate("""(n) => {
                        for (const b of document.querySelectorAll('button')) {
                            const t=(b.innerText||'').trim();
                            if (t === String(n)) {
                                const style=b.getAttribute('style')||'';
                                const m=style.match(/opacity:\\s*([\\d.]+)/);
                                const op=m?parseFloat(m[1]):1;
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
            # digits exist but none preferred usable -> take best usable
            if usable:
                pick_n = usable[0]['n']
                ok = await page.evaluate("""(n) => {
                    for (const b of document.querySelectorAll('button'))
                        if ((b.innerText||'').trim() === String(n)) { b.click(); return true; }
                    return false;
                }""", pick_n)
                if ok:
                    chosen = pick_n
                    break
        await asyncio.sleep(0.35)
    if dbg is not None:
        dbg.append(seen_log)
    return chosen

# ---------------- STRATEGY ----------------
def state(assigned):
    free = [q for q in range(1, 12) if q not in assigned]
    top_free = [q for q in free if q <= 7]
    bot_free = [q for q in free if q >= 8]
    bat = sum(p['b'] for q, p in assigned.items() if q <= 7)
    pow_ = sum(p['p'] for q, p in assigned.items() if q <= 7)
    bwl = sum(p['bl'] for q, p in assigned.items() if q >= 8)
    wk = any(p.get('wk') for p in assigned.values())
    n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
    return dict(free=free, top=top_free, bot=bot_free,
                bat=bat, pow=pow_, bwl=bwl, wk=wk, n70=n70)

def margins(st, c, q):
    kt = len(st['top']) - (1 if q <= 7 else 0)
    kb = len(st['bot']) - (1 if q >= 8 else 0)
    bat = st['bat'] + (c['b'] if q <= 7 else 0) + kt * FILL_B
    pow_ = st['pow'] + (c['p'] if q <= 7 else 0) + kt * FILL_P
    bwl = st['bwl'] + (c['bl'] if q >= 8 else 0) + kb * FILL_BL
    mb = (bat - THR_BAT) / max(1, kt + (1 if q <= 7 else 0))
    mp = (pow_ - THR_POW) / max(1, kt + (1 if q <= 7 else 0))
    ml = (bwl - THR_BWL) / max(1, kb + (1 if q >= 8 else 0))
    return mb, mp, ml

def choose_pick(squad, taken, assigned, want_wk_now=False):
    st = state(assigned)
    best, best_key = None, None
    for c in squad:
        if c['name'] in taken or not c.get('enabled'): continue
        is_wk = 'WK' in (c.get('role') or '') or c.get('wk')
        if want_wk_now and not is_wk and not st['wk']: continue
        for q in range(c['lo'], min(c['hi'], 11) + 1):
            if q not in st['free']: continue
            trial_bat = st['bat'] + (c['b'] if q <= 7 else 0)
            trial_pow = st['pow'] + (c['p'] if q <= 7 else 0)
            trial_bwl = st['bwl'] + (c['bl'] if q >= 8 else 0)
            kt = len(st['top']) - (1 if q <= 7 else 0)
            kb = len(st['bot']) - (1 if q >= 8 else 0)
            if trial_bat + kt * OPT_B < THR_BAT: continue
            if trial_pow + kt * OPT_P < THR_POW: continue
            if trial_bwl + kb * OPT_BL < THR_BWL: continue
            wk_after = st['wk'] or is_wk or (len(st['free']) - 1 >= 3)
            if not wk_after: continue
            mb, mp, ml = margins(st, c, q)
            wk_bonus = 2.5 if (is_wk and not st['wk']) else 0.0
            key = (min(mb, mp, ml) + wk_bonus, mb + mp + ml)
            if best_key is None or key > best_key:
                best_key, best = key, (c, q)
    return best

def squad_has_anchor(squad):
    """Require a genuine TOP-7 BATTING elite - bowler anchors don't fix the
    binding constraint (BAT/POW sums)."""
    for c in squad:
        if c['lo'] <= 7:
            if c['b'] >= 86 and c['p'] >= 88: return True
            if c['b'] >= 90 and c['p'] >= 85: return True
            if 'WK' in (c.get('role') or '') and c['b'] >= 84 and c['p'] >= 88: return True
    return False

def dead_end(assigned):
    """Optimistically infeasible -> abort session."""
    st = state(assigned)
    kt, kb = len(st['top']), len(st['bot'])
    wk_ok = st['wk'] or len(st['free']) >= 3
    return not (st['bat'] + kt*OPT_B >= THR_BAT and st['pow'] + kt*OPT_P >= THR_POW
                and st['bwl'] + kb*OPT_BL >= THR_BWL and wk_ok)

# ---------------- RESULT ----------------
WIN_KEYS  = ("500 CLUB", "YOU DID IT", "CHASED", "PERFECT CHASE", "HISTORY")
FAIL_KEYS = ("FELL SHORT", "HEARTBREAK", "ALL OUT", "SO CLOSE", "DENIED",
             "AGONY", "CRUEL", "LOST")

async def wait_result(page, sid, baseline_txt, timeout=120):
    """Only text lines NEW vs the pre-sim snapshot can trigger detection."""
    t0 = time.time()
    stale_dumped = False
    last_novel = ""
    stable = 0
    base_lines = {l.strip() for l in baseline_txt.splitlines()}
    while time.time() - t0 < timeout:
        cur_full = await body_text(page)
        novel = "\n".join(l for l in cur_full.splitlines()
                          if l.strip() and l.strip() not in base_lines)
        up = novel.upper()
        if up != last_novel:
            last_novel, stable = up, 0
        else:
            stable += 1
            if stable == 10 and not stale_dumped:
                stale_dumped = True
                await dump_text(page, f"result_stale_s{sid}.txt")
                await shot(page, f"s{sid}_stale")
        m = re.search(r"\b(\d{3,4})\s*/\s*(\d)\b", novel)
        ov = re.search(r"(\d{1,3}\.\d)\s*OVER", up)
        ctx = ("OVER" in up or "WICKET" in up or "BALL" in up or ov is not None
               or "SHORT" in up)
        win_hit = ((any(k in up for k in WIN_KEYS) or bool(re.search(r"\b500\s*/\s*0\b", novel)))
                   and ctx or ("500 CLUB" in up))
        fail_hit = any(k in up for k in FAIL_KEYS) or (m is not None and ctx and int(m.group(1)) < 500)
        if win_hit or fail_hit:
            await dump_text(page, f"result_s{sid}.txt")
            await shot(page, f"s{sid}_result")
            score = int(m.group(1)) if m else (500 if win_hit else None)
            return {"score": score,
                    "wkts": int(m.group(2)) if m else None,
                    "overs": ov.group(1) if ov else None,
                    "novel_preview": novel[:300],
                    "win": bool(win_hit or (score is not None and score >= 500)),
                    "timeout": False}
        for kw in ("SKIP",):
            if kw in up:
                await click_button_text(page, "SKIP", exact=True)
        await asyncio.sleep(0.8)
    await dump_text(page, f"result_timeout_s{sid}.txt")
    await shot(page, f"s{sid}_result_timeout")
    return {"score": None, "win": False, "timeout": True,
            "novel_preview": last_novel[:300]}

# ---------------- ONE DRAFT SESSION ----------------
async def draft_session(pw, sid):
    rec = {"session": sid, "ts": datetime.now().isoformat(), "reloads": 0,
           "reroll_used": False, "drafted": [], "success": False}
    browser = await pw.chromium.launch(headless=HEADLESS)
    ctx = await browser.new_context(viewport={"width": 480, "height": 1000})
    page = await ctx.new_page()
    try:
        # ---- phase 1: gated start
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
            if squad_has_anchor(squad):
                anchored = True
                log(f"  ANCHOR FOUND after {rec['reloads']} reload(s)")
                break
            rec["reloads"] += 1
        if not anchored:
            log("  no anchor after 40 reloads - proceeding anyway")

        # ---- phase 2: fill 11 slots with page-ground-truth verification
        assigned, taken = {}, set()
        rerolls_left = 1
        stall = 0
        while True:
            cnt, pos_map = await draft_truth(page)
            # sync internal state with reality
            assigned = {}
            for q, nm in pos_map.items():
                for d in rec["drafted"]:
                    if d["name"].upper() == nm:
                        assigned[q] = {k: d[k] for k in ("name", "b", "p", "bl")}
                        assigned[q]["wk"] = 'WK' in (d.get("role") or "")
            if cnt >= 11:
                break
            spin_no = cnt + 1
            squad = await read_squad(page)
            if len([c for c in squad if c['name'] not in taken]) < 2:
                ok = await click_button_text(page, "SPIN", exact=True)
                if not ok:
                    await asyncio.sleep(1.2)
                    await click_button_text(page, "SPIN", exact=True)
                squad = await wait_for_squad(page)

            st = state(assigned)
            want_wk = (not st['wk']) and spin_no >= WK_URGENT_SPIN
            choice = choose_pick(squad, taken, assigned, want_wk_now=want_wk)

            if (choice is not None and rerolls_left > 0 and spin_no <= 5
                    and len(st['top']) >= 3 and not want_wk):
                strong = any(c['lo'] <= 7 and c['b'] + c['p'] >= EARLY_REROLL_MIN_BP
                             for c in squad
                             if c['name'] not in taken and c.get('enabled'))
                if not strong:
                    log(f"  spin{spin_no}: weak squad -> early RE-ROLL")
                    if await click_button_text(page, "RE-ROLL"):
                        rerolls_left -= 1
                        rec["reroll_used"] = True
                        await asyncio.sleep(2.8)
                        squad = await wait_for_squad(page)
                        choice = choose_pick(squad, taken, assigned, want_wk)

            if choice is None and rerolls_left > 0 and not want_wk:
                log(f"  spin{spin_no}: no viable candidate -> RE-ROLL")
                if await click_button_text(page, "RE-ROLL"):
                    rerolls_left -= 1
                    rec["reroll_used"] = True
                    await asyncio.sleep(2.8)
                    squad = await wait_for_squad(page)
                    choice = choose_pick(squad, taken, assigned, want_wk)

            if choice is None:
                cand = [c for c in squad if c['name'] not in taken and c.get('enabled')]
                if not cand:
                    stall += 1
                    if stall > 3:
                        log("  dead end - restarting session")
                        return None
                    await asyncio.sleep(2)
                    continue
                fb, fq = None, None
                for c in cand:
                    for q in [x for x in range(c['lo'], min(c['hi'], 11)+1) if x in st['free']]:
                        mb, mp, ml = margins(st, c, q)
                        key = (min(mb, mp, ml), mb + mp + ml)
                        if fb is None or key > fb:
                            fb, fq = key, (c, q)
                choice = fq if fq else (cand[0], st['free'][0])
                log(f"  spin{spin_no}: FORCED {choice[0]['name']}")

            c, q_pref = choice
            log(f"  spin{spin_no}: pick {c['name']} (prefer pos {q_pref}) "
                f"[b={c['b']} p={c['p']} bl={c['bl']}"
                f"{' WK' if ('WK' in (c.get('role') or '')) else ''}]")
            clicked = await click_player_by_name(page, c['name'])
            pos_chosen = None
            if clicked:
                await asyncio.sleep(0.5)
                await shot(page, f"s{sid}_dbg{spin_no}_aftercard")
                try:
                    (LIVE_DIR / f"popup_s{sid}_{spin_no}.html").write_text(
                        await page.evaluate("() => document.body.innerHTML"),
                        encoding="utf-8")
                except Exception:
                    pass
                dbg = []
                pos_chosen = await choose_position(
                    page, [q_pref] + [x for x in range(1, 12) if x != q_pref], dbg=dbg)
                log(f"    popup: chose={pos_chosen} states={dbg[0][-3:] if dbg and dbg[0] else 'none'}")
                await shot(page, f"s{sid}_dbg{spin_no}_afterpos")
            elif (stall := stall + 1):
                pass

            # ---- verify registration against page truth
            registered = False
            for _ in range(12):
                await asyncio.sleep(0.6)
                cnt, pos_map = await draft_truth(page)
                if c['name'].upper() in pos_map.values():
                    registered = True
                    break
            if not registered:
                stall += 1
                log(f"    pick did NOT register (stall {stall})")
                if stall > 2:
                    return None
                continue
            stall = 0
            real_q = next(q for q, nm in pos_map.items() if nm == c['name'].upper())
            if real_q != q_pref:
                log(f"    landed at pos {real_q} (wanted {q_pref})")
            assigned[real_q] = dict(name=c['name'], b=c['b'], p=c['p'], bl=c['bl'],
                                    wk=('WK' in (c.get('role') or '')))
            taken.add(c['name'])
            rec["drafted"].append({"pos": real_q, "name": c['name'], "b": c['b'],
                                   "p": c['p'], "bl": c['bl'], "role": c['role']})

            if STRICT_ABORT and len(assigned) < 11 and dead_end(assigned):
                log("  state optimistically infeasible - aborting session")
                return None

        # ---- phase 3: simulate at TRUE 11/11
        cnt, pos_map = await draft_truth(page)
        if cnt < 11:
            log(f"  expected 11/11 but page says {cnt}/11 - aborting")
            return None
        bat7 = [assigned[q] for q in sorted(assigned) if q <= 7]
        bwl4 = [assigned[q] for q in sorted(assigned) if q >= 8]
        abat = sum(p['b'] for p in bat7) / max(1, len(bat7))
        apow = sum(p['p'] for p in bat7) / max(1, len(bat7))
        abwl = sum(p['bl'] for p in bwl4) / max(1, len(bwl4))
        n70 = sum(1 for p in assigned.values() if p['bl'] >= 70)
        has_wk = any(p['wk'] for p in assigned.values())
        will_win_tier = (has_wk and n70 >= 3 and abat >= 86 and apow >= 89 and abwl >= 90)
        rec["metrics"] = {"avg_bat_top7": round(abat, 2), "avg_pow_top7": round(apow, 2),
                          "avg_bwl_8_11": round(abwl, 2), "n_bwl_ge70": n70,
                          "has_wk": has_wk, "hits_all_thresholds": will_win_tier}
        log(f"  XI metrics: BAT={abat:.1f} POW={apow:.1f} BWL={abwl:.1f} "
            f"n70={n70} wk={has_wk} => {'TIER-1 (70% win)' if will_win_tier else 'sub-tier'}")

        await dump_text(page, f"presim_s{sid}.txt")
        baseline = await body_text(page)
        await asyncio.sleep(1.0)
        clicked_sim = False
        for label in ("SIMULATE", "START", "PLAY MATCH"):
            if await click_button_text(page, label, exact=True):
                clicked_sim = True
                break
        if not clicked_sim:
            clicked_sim = await click_button_text(page, "SPIN", exact=True)
            if clicked_sim:
                log("  (no SIMULATE label - used SPIN to start sim)")
        log(f"  simulation started: {clicked_sim}")
        if not clicked_sim:
            await dump_text(page, f"nosimbutton_s{sid}.txt")
            return None
        res = await wait_result(page, sid, baseline)
        rec.update(res)
        rec.pop("novel_preview", None)
        rec["success"] = bool(res.get("win"))
        emoji = "500 CLUB!" if res.get("win") else str(res.get("score"))
        log(f"  RESULT: {emoji} (timeout={res.get('timeout')})")
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
    global STRICT_ABORT
    max_drafts = int(os.environ.get("MAX_DRAFTS", "0")) or None
    stop_on_win = os.environ.get("STOP_ON_WIN", "1") == "1"
    STRICT_ABORT = os.environ.get("STRICT_ABORT", "1") == "1"
    total = wins = tier1 = aborts = 0
    log("=" * 62)
    log("  BOT v7.2 - page ground truth + diff-based result detection")
    log("=" * 62)
    async with async_playwright() as pw:
        while max_drafts is None or total < max_drafts:
            total += 1
            log(f"\n===== DRAFT #{total} | wins so far: {wins} =====")
            rec = None
            for retry in range(4):
                rec = await draft_session(pw, total)
                if rec is not None:
                    break
                aborts += 1
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
    log(f"FINAL: {wins} wins / {total} drafts | tier-1 teams: {tier1} | aborted sessions: {aborts}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nstopped by user")
