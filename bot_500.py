"""
500/0 INFINITE DRAFT BOT
========================
Automates the 500-0.com cricket draft game using Playwright.
Strategy based on analysis of top 250 winning teams from the 500 Club.

INSTALL: pip install playwright && playwright install chromium
RUN:     python bot_500.py

How it works:
  1. Opens 500-0.com in a visible browser (so you can watch).
  2. Spins the wheel. If the squad doesn't contain any MUST-HAVE players
     → reloads and spins again (infinite loop until good squad).
  3. Picks the best available player from the squad for each slot.
  4. Uses the single REROLL (2nd spin swap) wisely on a weak slot.
  5. Simulates and records the result.
  6. Repeats forever, appending every run to run_log.json.
"""

import asyncio
import json
import time
import random
from pathlib import Path
from datetime import datetime
from collections import defaultdict

try:
    from playwright.async_api import async_playwright, TimeoutError as PWTimeout
except ImportError:
    print("Install playwright first:  pip install playwright && playwright install chromium")
    raise

# ──────────────────────────────────────────────────────────────────────────────
# ❶  STRATEGY DATA  (derived from analysis of 250 winning 500-Club teams)
# ──────────────────────────────────────────────────────────────────────────────

# Players that appear in ≥40% of all winning teams (LIVE DATA from 100 teams).
# If NONE of these appear in the FIRST spin, we reload.
MUST_HAVE = {
    "AB de Villiers",         # WK   — 86% of winners ← #1 most essential
    "Viv Richards",           # BAT  — 77%
    "Muttiah Muralitharan",   # BWL  — 65%
    "Virat Kohli",            # BAT  — 53%
    "Sachin Tendulkar",       # BAT  — 52%
    "Heinrich Klaasen",       # WK   — 50%
    "Jos Buttler",            # WK   — 43%
    "Shane Warne",            # BWL  — 42%
}

# Minimum 2 of these must appear in Slot 1-7 (batters zone) for first spin to be "good"
ELITE_BATTERS = {
    "Viv Richards", "Sachin Tendulkar", "Virat Kohli", "Brian Lara",
    "Rohit Sharma", "AB de Villiers", "Sanath Jayasuriya", "Chris Gayle",
    "Travis Head", "Babar Azam", "Virender Sehwag", "David Warner",
    "Heinrich Klaasen", "Jos Buttler", "MS Dhoni", "Adam Gilchrist",
}

# Elite bowlers for the lower-order slots 8-11
ELITE_BOWLERS = {
    "Muttiah Muralitharan", "Wasim Akram", "Malcolm Marshall", "Shane Warne",
    "Curtly Ambrose", "Mitchell Starc", "Rashid Khan", "Waqar Younis",
    "Lasith Malinga", "Dale Steyn", "Glenn McGrath", "Trent Boult",
    "Joel Garner", "Allan Donald", "Shoaib Akhtar", "Jasprit Bumrah",
    "Shane Bond", "Saeed Ajmal",
}

# Priority order: pick the highest-ranked player available for each slot.
# Batters (slots 1-7):  bat average > power > all-round ability
BATTER_PRIORITY = [
    "Viv Richards", "Sachin Tendulkar", "Brian Lara", "Virat Kohli",
    "Rohit Sharma", "AB de Villiers", "Adam Gilchrist", "Sanath Jayasuriya",
    "Chris Gayle", "Travis Head", "Jos Buttler", "Heinrich Klaasen",
    "Babar Azam", "MS Dhoni", "Virender Sehwag", "David Warner",
    "Kumar Sangakkara", "Aravinda de Silva", "Kevin Pietersen",
    "Lance Klusener", "Shahid Afridi", "Glenn Maxwell", "Jonny Bairstow",
    "Nicholas Pooran", "Michael Bevan", "Andrew Flintoff", "Wanindu Hasaranga",
    "Daryl Mitchell", "Hashim Amla",
]

BOWLER_PRIORITY = [
    "Muttiah Muralitharan", "Wasim Akram", "Malcolm Marshall", "Shane Warne",
    "Curtly Ambrose", "Rashid Khan", "Mitchell Starc", "Waqar Younis",
    "Lasith Malinga", "Dale Steyn", "Glenn McGrath", "Joel Garner",
    "Trent Boult", "Allan Donald", "Shoaib Akhtar", "Jasprit Bumrah",
    "Shane Bond", "Saeed Ajmal", "Anil Kumble", "Imran Khan",
    "Shaun Pollock", "Lance Klusener", "Shaheen Afridi", "Jofra Archer",
]

# Log file
LOG_FILE = Path("run_log.json")

# ──────────────────────────────────────────────────────────────────────────────
# ❷  HELPER FUNCTIONS
# ──────────────────────────────────────────────────────────────────────────────

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")

def save_run(record):
    runs = []
    if LOG_FILE.exists():
        try:
            runs = json.loads(LOG_FILE.read_text())
        except Exception:
            runs = []
    runs.append(record)
    LOG_FILE.write_text(json.dumps(runs, indent=2))

def spin_is_good(squad_names: list[str]) -> bool:
    """Check if the first spin is worth keeping."""
    hits = MUST_HAVE & set(squad_names)
    elite_bat_hits = ELITE_BATTERS & set(squad_names)
    elite_bwl_hits = ELITE_BOWLERS & set(squad_names)
    # Need at least 1 must-have, 2 elite batters, 2 elite bowlers
    return len(hits) >= 1 and len(elite_bat_hits) >= 2 and len(elite_bwl_hits) >= 2

def choose_player(available: list[str], slot: int, drafted: set[str], is_bowler_slot: bool) -> str | None:
    """Choose the best available player for the given slot."""
    priority = BOWLER_PRIORITY if is_bowler_slot else BATTER_PRIORITY
    for name in priority:
        if name in available and name not in drafted:
            return name
    # Fallback: pick first available
    for name in available:
        if name not in drafted:
            return name
    return None

def should_reroll(slot: int, chosen: str | None, is_bowler_slot: bool) -> bool:
    """Decide whether to use the 1-time reroll on the 2nd spin."""
    if chosen is None:
        return True
    ref = BOWLER_PRIORITY if is_bowler_slot else BATTER_PRIORITY
    rank = ref.index(chosen) if chosen in ref else 999
    return rank > 8   # Use reroll if chosen is outside top-8 priority

# ──────────────────────────────────────────────────────────────────────────────
# ❸  PLAYWRIGHT AUTOMATION
# ──────────────────────────────────────────────────────────────────────────────

URL = "https://500-0.com"
HEADLESS = False    # Set True for background/faster runs

async def wait_for(page, selector, timeout=15000):
    return await page.wait_for_selector(selector, timeout=timeout)

async def get_squad_names(page) -> list[str]:
    """Extract player names from the current squad shown after spinning."""
    # The game renders player cards — find all player name elements
    # Selector may vary; try multiple patterns.
    names = []
    for sel in [
        "[data-testid='player-name']",
        ".player-name",
        ".player-card .name",
        "[class*='PlayerName']",
        "[class*='player'] span",
    ]:
        try:
            els = await page.query_selector_all(sel)
            if els:
                names = [await el.inner_text() for el in els]
                names = [n.strip() for n in names if n.strip()]
                if len(names) >= 10:
                    break
        except Exception:
            pass
    if not names:
        # JS fallback — scrape everything that looks like a player name
        names = await page.evaluate("""() => {
            const nodes = document.querySelectorAll('*');
            const found = [];
            nodes.forEach(n => {
                const t = (n.innerText || '').trim();
                if (n.children.length === 0 && t.length > 3 && t.length < 40
                    && /^[A-Z]/.test(t) && !t.includes('\\n'))
                    found.push(t);
            });
            return [...new Set(found)];
        }""")
    return [n for n in names if n]

async def click_player(page, name: str) -> bool:
    """Click a player card by name."""
    # Try clicking a button/div containing the player's name
    escaped = name.replace("'", "\\'")
    result = await page.evaluate(f"""() => {{
        const els = document.querySelectorAll('button, [role="button"], [class*="player"], [class*="Player"]');
        for (const el of els) {{
            if ((el.innerText || '').includes('{escaped}')) {{
                el.click();
                return true;
            }}
        }}
        return false;
    }}""")
    return result

async def click_spin(page) -> bool:
    """Click the Spin button."""
    for sel in [
        "text=SPIN",
        "text=Spin",
        "[data-testid='spin-btn']",
        "button:has-text('SPIN')",
        "button:has-text('Spin')",
        "[class*='spin']",
        "[class*='Spin']",
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                return True
        except Exception:
            pass
    return False

async def click_simulate(page) -> bool:
    """Click the Simulate / Chase button."""
    for sel in [
        "text=SIMULATE",
        "text=Simulate",
        "text=CHASE",
        "button:has-text('SIMULATE')",
        "button:has-text('Chase')",
        "[data-testid='simulate-btn']",
    ]:
        try:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click()
                return True
        except Exception:
            pass
    return False

async def get_score(page) -> dict:
    """Extract the final score from the result page."""
    await asyncio.sleep(3)  # let animation finish
    score_text = await page.evaluate("""() => {
        const body = document.body.innerText;
        return body;
    }""")
    result = {
        "score": None,
        "overs": None,
        "success": False,
        "raw_snippet": score_text[:500] if score_text else ""
    }
    import re
    # Look for score patterns like "507/3" or "499/8"
    m = re.search(r'(\d{3,4})/(\d)', score_text)
    if m:
        result["score"] = int(m.group(1))
        result["success"] = result["score"] >= 500
    return result

# ──────────────────────────────────────────────────────────────────────────────
# ❹  MAIN DRAFT LOOP
# ──────────────────────────────────────────────────────────────────────────────

async def run_draft_session(page, session_id: int) -> dict:
    record = {
        "session": session_id,
        "timestamp": datetime.now().isoformat(),
        "spins": 0,
        "reloads": 0,
        "reroll_used": False,
        "drafted": [],
        "score": None,
        "success": False
    }

    await page.goto(URL, wait_until="networkidle")
    await asyncio.sleep(2)

    # ── Phase 1: First spin – reload until good squad ──────────────────────────
    log(f"Session {session_id}: Looking for a good first squad…")
    while True:
        spun = await click_spin(page)
        if not spun:
            log("  Could not find SPIN button – reloading page")
            await page.reload(wait_until="networkidle")
            await asyncio.sleep(2)
            continue

        record["spins"] += 1
        await asyncio.sleep(3)   # wait for squad to render

        squad_names = await get_squad_names(page)
        log(f"  Spin #{record['spins']}: {len(squad_names)} players found")

        if spin_is_good(squad_names):
            log(f"  ✓ Good squad! Must-haves present: {MUST_HAVE & set(squad_names)}")
            break
        else:
            log(f"  ✗ Weak squad. Must-haves found: {MUST_HAVE & set(squad_names)}. Reloading…")
            await page.reload(wait_until="networkidle")
            record["reloads"] += 1
            await asyncio.sleep(2)

    # ── Phase 2: Draft players, slot by slot ───────────────────────────────────
    drafted = set()
    reroll_available = True

    for slot in range(1, 12):
        is_bowler_slot = slot >= 8

        # Spin to get next squad (except the first slot where we already have it)
        if slot > 1:
            spun = await click_spin(page)
            record["spins"] += 1
            await asyncio.sleep(3)
            squad_names = await get_squad_names(page)

        available = [n for n in squad_names if n not in drafted]
        chosen = choose_player(available, slot, drafted, is_bowler_slot)

        # ── Reroll logic (2nd spin swap, usable once) ──────────────────────────
        if reroll_available and slot >= 2 and should_reroll(slot, chosen, is_bowler_slot):
            log(f"  Slot {slot}: Using REROLL (current best: {chosen})")
            # Try to click the reroll/swap button
            rerolled = await page.evaluate("""() => {
                const els = document.querySelectorAll('button');
                for (const el of els) {
                    const t = (el.innerText || '').toUpperCase();
                    if (t.includes('REROLL') || t.includes('SWAP') || t.includes('NEW')) {
                        el.click(); return true;
                    }
                }
                return false;
            }""")
            if rerolled:
                reroll_available = False
                record["reroll_used"] = True
                record["spins"] += 1
                await asyncio.sleep(3)
                squad_names = await get_squad_names(page)
                available = [n for n in squad_names if n not in drafted]
                chosen = choose_player(available, slot, drafted, is_bowler_slot)
                log(f"  Slot {slot}: After reroll, picking → {chosen}")

        if chosen:
            success = await click_player(page, chosen)
            if success:
                drafted.add(chosen)
                record["drafted"].append({"slot": slot, "name": chosen})
                log(f"  Slot {slot}: Drafted → {chosen}")
            else:
                log(f"  Slot {slot}: ⚠ Could not click {chosen}")
        else:
            log(f"  Slot {slot}: ⚠ No suitable player found!")

        await asyncio.sleep(1)

    # ── Phase 3: Simulate ──────────────────────────────────────────────────────
    log(f"Session {session_id}: Simulating chase…")
    await click_simulate(page)
    await asyncio.sleep(8)   # wait for full animation

    result = await get_score(page)
    record.update(result)

    emoji = "🏆" if result["success"] else "❌"
    log(f"  {emoji} Score: {result.get('score')} | Success: {result['success']}")

    return record


async def main():
    runs_completed = 0
    successes = 0

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=HEADLESS, slow_mo=300)
        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        log("=" * 60)
        log("  500/0 INFINITE DRAFT BOT — STARTING")
        log("  Press Ctrl-C to stop")
        log("=" * 60)

        while True:
            try:
                runs_completed += 1
                record = await run_draft_session(page, runs_completed)
                save_run(record)
                if record["success"]:
                    successes += 1
                log(f"  Run #{runs_completed} done. Total 500s: {successes}/{runs_completed}")
                await asyncio.sleep(2)
            except KeyboardInterrupt:
                log("Stopping bot.")
                break
            except Exception as e:
                log(f"  ERROR in run #{runs_completed}: {e}")
                try:
                    await page.reload(wait_until="networkidle")
                except Exception:
                    pass
                await asyncio.sleep(3)

        await browser.close()
    log(f"Final: {successes} 500s in {runs_completed} runs.")


if __name__ == "__main__":
    asyncio.run(main())
