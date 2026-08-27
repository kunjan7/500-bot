"""
500/0 BOT v5 - Fixed name parsing + optimal strategy
=====================================================
Fix: Button text = "Chris Gayle BATTER1-2 85BAT 94POW 40BWL"
     Split on BATTER/WK/BOWLER/ALL-ROUNDER to extract clean name.

Strategy improvements:
  - Fix player name extraction from squad buttons
  - Add ratings-based decision making (read actual BAT/POW/BWL)
  - Handle greyed-out (illegal) slots correctly
  - Position assignment: highest POW batters at 1-3, high BAT at 4-6

RUN:  python bot_v5.py
"""

import asyncio
import json
import re
import sys
import pathlib
from datetime import datetime
from playwright.async_api import async_playwright

sys.stdout.reconfigure(encoding="utf-8")

URL      = "https://500-0.com"
HEADLESS = False
SLOW_MO  = 250
LOG_FILE = pathlib.Path("run_log_v5.json")
SHOT_DIR = pathlib.Path("screenshots"); SHOT_DIR.mkdir(exist_ok=True)

# ── PLAYER PRIORITY (name-only, for fallback if ratings unavailable) ──────────
BATTER_PRIORITY = [
    "Viv Richards", "AB de Villiers", "Sachin Tendulkar", "Brian Lara",
    "Virat Kohli", "Rohit Sharma", "Chris Gayle", "Sanath Jayasuriya",
    "Adam Gilchrist", "Travis Head", "Jos Buttler", "Heinrich Klaasen",
    "Babar Azam", "MS Dhoni", "Virender Sehwag", "David Warner",
    "Kumar Sangakkara", "Aravinda de Silva", "Kevin Pietersen",
    "Ricky Ponting", "Steve Waugh", "Jonny Bairstow", "Nicholas Pooran",
    "Michael Bevan", "Glenn Maxwell", "Lance Klusener", "Shahid Afridi",
    "Daryl Mitchell", "Hashim Amla", "Dean Jones", "Ross Taylor",
    "Mark Waugh", "Matthew Hayden", "Inzamam-ul-Haq", "Sourav Ganguly",
    "Jacques Kallis", "Andrew Flintoff", "Kieron Pollard", "Ben Stokes",
    "Yuvraj Singh", "Mahela Jayawardene",
]

BOWLER_PRIORITY = [
    "Muttiah Muralitharan", "Wasim Akram", "Malcolm Marshall", "Shane Warne",
    "Curtly Ambrose", "Rashid Khan", "Mitchell Starc", "Waqar Younis",
    "Lasith Malinga", "Dale Steyn", "Glenn McGrath", "Joel Garner",
    "Trent Boult", "Allan Donald", "Shoaib Akhtar", "Jasprit Bumrah",
    "Shane Bond", "Saeed Ajmal", "Anil Kumble", "Imran Khan",
    "Shaun Pollock", "Shaheen Afridi", "Jofra Archer", "Brett Lee",
    "Zaheer Khan", "Chaminda Vaas", "Andy Roberts", "Michael Holding",
    "Saqlain Mushtaq", "Mushtaq Ahmed", "Aqib Javed", "Waqar Younis",
]

MUST_HAVE_ANY = {
    "AB de Villiers", "Viv Richards", "Muttiah Muralitharan", "Virat Kohli",
    "Sachin Tendulkar", "Heinrich Klaasen", "Jos Buttler", "Shane Warne",
    "Malcolm Marshall", "Wasim Akram", "Brian Lara", "Rohit Sharma",
    "Chris Gayle", "Adam Gilchrist", "MS Dhoni", "Rashid Khan",
    "Lance Klusener", "Shahid Afridi", "Imran Khan", "Curtly Ambrose",
}

# ── PARSE SQUAD BUTTONS ───────────────────────────────────────────────────────
def parse_player_button(btn_text: str) -> dict | None:
    """
    Parse a button like: "Chris Gayle BATTER1–285BAT94POW40BWL"
    or:                  "Mushtaq Ahmed BOWLER9–1126BAT50POW80BWL"
    Returns: {name, role, bat, pow, bwl, slot_min, slot_max, full_text}
    """
    t = btn_text.strip()
    if not t or len(t) < 5:
        return None

    # Role keywords that appear right after the name
    role_kw = r"(BATTER|WK|BOWLER|ALL-ROUNDER|AR|WICKET-KEEPER)"

    m = re.match(r"^([A-Z][A-Za-z '.]+?)\s+" + role_kw, t)
    if not m:
        # Try first line only (in case newline-split didn't happen)
        first = t.split('\n')[0].strip()
        m = re.match(r"^([A-Z][A-Za-z '.]+?)\s+" + role_kw, first)
        if not m:
            return None

    name = m.group(1).strip()
    role = m.group(2)

    # Extract numbers: slot range and ratings
    nums = re.findall(r'\d+', t)
    nums = [int(n) for n in nums]

    # Slot range: first 2 small numbers (1-11), ratings: 3 numbers 0-99
    slot_nums = [n for n in nums if 1 <= n <= 11]
    rating_nums = [n for n in nums if 1 <= n <= 99]

    slot_min = slot_nums[0] if slot_nums else 1
    slot_max = slot_nums[1] if len(slot_nums) >= 2 else slot_min

    # Find 3 consecutive ratings (bat, pow, bwl)
    bat = pow_ = bwl = 0
    for i in range(len(rating_nums) - 2):
        a, b, c = rating_nums[i], rating_nums[i+1], rating_nums[i+2]
        if all(1 <= x <= 99 for x in [a, b, c]):
            bat, pow_, bwl = a, b, c
            break

    return {
        "name": name,
        "role": role,
        "bat": bat, "pow": pow_, "bwl": bwl,
        "slot_min": slot_min, "slot_max": slot_max,
        "full": t,
    }

# ── BEST PLAYER SELECTION ─────────────────────────────────────────────────────
def best_player_for_slot(squad: list, slot: int, drafted: set) -> dict | None:
    is_bowler = slot >= 8
    # Filter: not drafted, and this slot is legal for player
    ok = [p for p in squad if p["name"] not in drafted and p["slot_min"] <= slot <= p["slot_max"]]
    if not ok:
        # Relax constraint — allow any if no legal player
        ok = [p for p in squad if p["name"] not in drafted]

    if not ok:
        return None

    priority = BOWLER_PRIORITY if is_bowler else BATTER_PRIORITY

    # 1) Try priority list first
    for target in priority:
        for p in ok:
            if p["name"] == target:
                return p

    # 2) If no priority match, use ratings
    if is_bowler:
        return max(ok, key=lambda p: p["bwl"])
    else:
        return max(ok, key=lambda p: p["bat"] + p["pow"])

def squad_good(squad: list) -> bool:
    names = {p["name"] for p in squad}
    return bool(MUST_HAVE_ANY & names)

# ── HELPERS ───────────────────────────────────────────────────────────────────
def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def save_run(rec):
    runs = []
    if LOG_FILE.exists():
        try: runs = json.loads(LOG_FILE.read_text(encoding="utf-8"))
        except: pass
    runs.append(rec)
    LOG_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")

async def shot(page, name):
    try: await page.screenshot(path=str(SHOT_DIR / name))
    except: pass

async def click_btn(page, text: str, partial=True) -> bool:
    btns = await page.query_selector_all("button")
    for btn in btns:
        try:
            t = (await btn.inner_text()).strip()
            if partial and text.upper() in t.upper():
                await btn.click(); return True
            elif not partial and t.upper() == text.upper():
                await btn.click(); return True
        except: pass
    return False

# ── GET SQUAD FROM PAGE ───────────────────────────────────────────────────────
async def get_squad(page) -> list[dict]:
    """Parse all player cards from current squad panel."""
    btn_texts = await page.evaluate("""() => {
        const txts = [];
        document.querySelectorAll('button').forEach(b => {
            const t = (b.innerText || b.textContent || '').trim();
            if (t) txts.push(t);
        });
        return txts;
    }""")

    players = []
    seen = set()
    for t in btn_texts:
        p = parse_player_button(t)
        if p and p["name"] not in seen and len(p["name"]) >= 5:
            players.append(p)
            seen.add(p["name"])

    return players

# ── CLICK PLAYER ──────────────────────────────────────────────────────────────
async def click_player(page, player: dict) -> bool:
    name = player["name"]
    escaped = name.replace("'", "\\'")

    # Find button whose first line matches the name exactly
    ok = await page.evaluate(f"""() => {{
        const target = '{escaped}';
        for (const btn of document.querySelectorAll('button')) {{
            const line0 = (btn.innerText || '').trim().split('\\n')[0].trim();
            if (line0 === target || (btn.innerText||'').trim().startsWith(target + ' ') ||
                (btn.innerText||'').trim().startsWith(target + '\\n')) {{
                btn.click();
                return true;
            }}
        }}
        return false;
    }}""")
    return bool(ok)

# ── HANDLE POSITION POPUP ─────────────────────────────────────────────────────
async def handle_pos_popup(page, slot: int) -> bool:
    await asyncio.sleep(0.6)
    popup = await page.evaluate("""() => {
        for (const el of document.querySelectorAll('div, section')) {
            if ((el.innerText||'').includes('batting position')) return true;
        }
        return false;
    }""")
    if not popup:
        return False

    pos_nums = await page.evaluate("""() => {
        const nums = [];
        document.querySelectorAll('button').forEach(b => {
            const t = (b.innerText||'').trim();
            const n = parseInt(t);
            if (String(n) === t && n >= 1 && n <= 11) nums.push(n);
        });
        return nums;
    }""")

    log(f"    Pos popup! Available: {pos_nums}")
    if not pos_nums:
        return False

    # Pick position closest to the slot number
    target = min(pos_nums, key=lambda x: abs(x - slot))
    log(f"    Clicking position {target}")

    await page.evaluate(f"""() => {{
        for (const btn of document.querySelectorAll('button')) {{
            if ((btn.innerText||'').trim() === '{target}') {{ btn.click(); return; }}
        }}
    }}""")
    await asyncio.sleep(0.4)
    return True

# ── RESULT EXTRACTION ─────────────────────────────────────────────────────────
async def get_result(page) -> dict:
    log("  Simulating (25s)...")
    await asyncio.sleep(25)
    body = await page.evaluate("() => document.body.innerText")
    res = {"score": None, "wkts": None, "overs": None, "success": False, "snippet": body[:400]}

    m = re.search(r'(\d{3,4})[/\-](\d)', body)
    if m:
        res["score"] = int(m.group(1)); res["wkts"] = int(m.group(2))
        res["success"] = res["score"] >= 500

    m2 = re.search(r'(\d{2})\.(\d)\s*over', body)
    if m2:
        res["overs"] = f"{m2.group(1)}.{m2.group(2)}"

    if any(kw in body.upper() for kw in ["500 CLUB", "YOU DID IT", "CHASED", "CONGRATULATIONS"]):
        res["success"] = True

    return res

# ── DRAFT SESSION ─────────────────────────────────────────────────────────────
async def draft_session(page, sid: int, attempt: int = 1) -> dict:
    if attempt > 20:
        return {"session": sid, "error": "Too many reload attempts", "success": False}

    rec = {
        "session": sid, "attempt": attempt,
        "ts": datetime.now().isoformat(),
        "drafted": [], "success": False,
    }

    try:
        await page.goto(URL, wait_until="networkidle")
        await asyncio.sleep(2)

        # Select EASY + DRAFT
        log("  EASY → DRAFT")
        await click_btn(page, "EASY")
        await asyncio.sleep(0.5)
        await click_btn(page, "DRAFT")
        await asyncio.sleep(3)

        # Spin #1
        log("  Spin #1...")
        await click_btn(page, "SPIN")
        await asyncio.sleep(4.5)
        await shot(page, f"v5_r{sid}_spin1.png")

        squad = await get_squad(page)
        log(f"  Squad ({len(squad)} players): {[p['name'] for p in squad]}")

        if not squad:
            log("  No squad found! Retrying...")
            return await draft_session(page, sid, attempt + 1)

        # RE-ROLL if weak
        if not squad_good(squad):
            log(f"  Weak squad — RE-ROLLING")
            rerolled = await click_btn(page, "RE-ROLL")
            if not rerolled:
                rerolled = await click_btn(page, "REROLL")
            if rerolled:
                await asyncio.sleep(3.5)
                squad = await get_squad(page)
                log(f"  After reroll: {[p['name'] for p in squad]}")
            else:
                log("  RE-ROLL failed, restarting...")
                return await draft_session(page, sid, attempt + 1)

        drafted = set()

        for slot in range(1, 12):
            is_bwl = slot >= 8
            log(f"\n  Slot {slot} ({'BWL' if is_bwl else 'BAT'})")

            # Spin for slots 2-11
            if slot > 1:
                ok = await click_btn(page, "SPIN")
                if not ok:
                    await asyncio.sleep(1.5)
                    ok = await click_btn(page, "SPIN")
                await asyncio.sleep(4)
                squad = await get_squad(page)
                log(f"  Squad: {[p['name'] for p in squad]}")

            player = best_player_for_slot(squad, slot, drafted)
            if not player:
                log(f"  No player for slot {slot}!")
                continue

            log(f"  Pick: {player['name']} [BAT={player['bat']} POW={player['pow']} BWL={player['bwl']}]")

            ok = await click_player(page, player)
            if not ok:
                log(f"  Click failed — fallback to first available")
                for p in squad:
                    if p["name"] not in drafted:
                        ok = await click_player(page, p)
                        if ok:
                            player = p; break

            await handle_pos_popup(page, slot)
            await asyncio.sleep(1)

            drafted.add(player["name"])
            rec["drafted"].append({
                "slot": slot, "name": player["name"],
                "bat": player["bat"], "pow": player["pow"], "bwl": player["bwl"],
                "must_have": player["name"] in MUST_HAVE_ANY,
            })
            log(f"  ✓ {player['name']}")
            await shot(page, f"v5_r{sid}_s{slot:02d}.png")

        # Simulate
        log("\n  Drafting complete. Simulating...")
        await asyncio.sleep(1.5)
        await shot(page, f"v5_r{sid}_presim.png")

        sim = await click_btn(page, "SIMULATE")
        if not sim: sim = await click_btn(page, "CHASE")
        if not sim: sim = await click_btn(page, "GO")

        res = await get_result(page)
        rec.update(res)
        await shot(page, f"v5_r{sid}_result.png")

        log(f"\n  {'✅ 500!' if res['success'] else '❌'} Score: {res['score']}/{res['wkts']} in {res['overs']} overs")

    except Exception as e:
        import traceback; traceback.print_exc()
        rec["error"] = str(e)

    return rec

# ── MAIN ──────────────────────────────────────────────────────────────────────
async def main():
    total = 0; fives = 0
    log("="*60)
    log("  500/0 BOT v5 — FIXED NAME PARSING + SMART STRATEGY")
    log("  Ctrl+C to stop")
    log("="*60)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=SLOW_MO)
        ctx = await browser.new_context(viewport={"width":1280,"height":900})
        page = await ctx.new_page()

        while True:
            try:
                total += 1
                log(f"\n{'='*60}\n  RUN #{total} | 500s: {fives}/{total-1}\n{'='*60}")
                rec = await draft_session(page, total)
                save_run(rec)
                if rec.get("success"):
                    fives += 1
                    log(f"🏆🏆 500! Total: {fives}/{total}")
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                break
            except Exception as e:
                log(f"OUTER ERROR: {e}")
                try: await page.reload()
                except: pass
                await asyncio.sleep(3)

        log(f"\nFINAL: {fives} x 500s in {total} runs")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
