"""
spin_hack.py — intercept 500-0.com's spin to always get our desired team.

PROVEN MECHANISM:
  page.route() injects window.__vo, window.__f6, window.__a6 into the bundle.
  Math.random() is patched to return our desired index when the game picks a team
  via Mt[Math.floor(Math.random()*Mt.length)].

FLOW: Home -> EASY -> DRAFT -> (SPIN -> pick player) x11 -> SIMULATE -> SKIP TO END
"""
import asyncio, json, re, time, random, os, sys
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
LIVE_DIR = Path(__file__).parent / "live"
SHOTS_DIR = Path(__file__).parent / "shots_hack"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "kunjan1387")
MAX_DRAFTS = int(os.getenv("MAX_DRAFTS", "3"))
STOP_ON_WIN = os.getenv("STOP_ON_WIN", "1") == "1"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


async def setup_route_interception(page):
    async def intercept(route):
        resp = await route.fetch()
        body = await resp.text()
        if "window.__f6" not in body:
            body = body.replace(
                "analysis:Z}}var Mc=",
                "analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc=",
            )
            body = body.replace(
                "];function c6(){",
                "];window.__vo=vo;window.__K2=K2;function c6(){",
            )
            # Capture the game's actual team pool right before Math.random picks a team
            # Also capture the RESULT of the selection (the team object itself)
            body = body.replace(
                "Mt[Math.floor(Math.random()*Mt.length)]",
                "(window.__gamePool=Mt,window.__lastSpinResult=Mt[Math.floor(Math.random()*Mt.length)])",
            )
        await route.fulfill(response=resp, body=body, content_type="application/javascript")
    await page.route("**/*app*.js", intercept)


# Inject Math.random patch + __chooseTeam helper + __readCards helper
INJECT_HACK_JS = r"""
(() => {
    if (window.__hackReady) return;
    window.__hackReady = true;

    // ── PRNG patch ──
    const _orig = Math.random;
    let _s = SEED;
    function _prng() {
        _s = _s + 1831565813 | 0;
        let t = Math.imul(_s ^ _s >>> 15, 1 | _s);
        t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t;
        return ((t ^ t >>> 14) >>> 0) / 4294967296;
    }

    window.__h = {
        on: true, idx: -1, poolSz: 1, overrideReady: false,
        picked: [], openSlots: [1,2,3,4,5,6,7,8,9,10,11],
        usage: {}, rerollTeam: null,
    };

    Math.random = function() {
        const h = window.__h;
        if (!h.on) return _orig();
        if (h.overrideReady && h.idx >= 0) {
            // Read the ACTUAL game pool size (captured by our route injection)
            const actualPoolSz = (window.__gamePool || []).length || h.poolSz;
            const v = (h.idx + 0.5) / actualPoolSz;
            h.idx = -1; h.overrideReady = false;
            return Math.min(Math.max(v, 1e-6), 0.999999);
        }
        return _prng();
    };

    // ── Team picker (runs entirely in page, returns pool-ordered index) ──
    window.__chooseTeam = function(need) {
        const vo = window.__vo, h = window.__h;
        if (!vo || !h) return null;
        const picked = new Set(h.picked.map(p => p.name));
        const slots = [...h.openSlots];
        const K2 = window.__K2 || 2;
        const pool = vo.filter(t => {
            if (!t.players.some(p => !picked.has(p.n) && slots.some(s => s >= p.r[0] && s <= p.r[1])))
                return false;
            if ((h.usage[t.id] || 0) >= K2) return false;
            if (h.rerollTeam && t.id === h.rerollTeam) return false;
            return true;
        });
        if (!pool.length) return null;

        function sc(team) {
            let s = 0;
            for (const p of team.players) {
                if (p.b >= 90) s += 15; else if (p.b >= 86) s += 10; else if (p.b >= 82) s += 5;
                if (p.p >= 90) s += 12; else if (p.p >= 88) s += 8;
                if (p.bl >= 90) s += 12; else if (p.bl >= 80) s += 4; else if (p.bl >= 70) s += 2;
                if (p.wk) s += 6;
            }
            if (need === "bat") for (const p of team.players) if (p.b >= 88) s += 20;
            else if (need === "bowl") for (const p of team.players) { if (p.bl >= 90) s += 15; else if (p.bl >= 70) s += 5; }
            else if (need === "wk") for (const p of team.players) if (p.wk && p.b >= 80) s += 20;
            return s;
        }

        let bi = 0, bs = -1, bn = "";
        pool.forEach((t, i) => { const s = sc(t); if (s > bs) { bs = s; bi = i; bn = t.name + " " + t.season; } });
        return { idx: bi, poolSize: pool.length, team: bn, score: bs };
    };

    // ── Card reader (bot_v4 proven parser — extracts BAT/POW/BWL) ──
    window.__readCards = function() {
        const out = [];
        const seen = new Set();
        for (const b of document.querySelectorAll('button')) {
            const t = b.innerText || '';
            if (!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue;
            if (!/BAT/.test(t)) continue;
            const st = b.getAttribute('style') || '';
            const om = st.match(/opacity:\s*([\d.]+)/);
            if (om && parseFloat(om[1]) < 0.85) continue;
            const lines = t.split('\n').map(s => s.trim()).filter(Boolean);
            let name = null, role = '', lo = 1, hi = 11, bb = 0, pp = 0, bl = 0;
            for (let i = 0; i < lines.length; i++) {
                const L = lines[i];
                if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) { role = L.toUpperCase(); continue; }
                const rm = L.match(/^(\d{1,2})[-\u2013](\d{1,2})$/);
                if (rm) { lo = +rm[1]; hi = +rm[2]; continue; }
                if (/^BAT$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { bb = +lines[i-1]; continue; }
                if (/^POW$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { pp = +lines[i-1]; continue; }
                if (/^BWL$/i.test(L) && i > 0 && /^\d+$/.test(lines[i-1])) { bl = +lines[i-1]; continue; }
            }
            if (!name) {
                for (const L of lines) {
                    if (/^(BATTER|BOWLER|ALL-ROUNDER|WK)$/i.test(L)) continue;
                    if (/^\d/.test(L)) continue;
                    if (/^(BAT|POW|BWL)$/i.test(L)) continue;
                    name = L; break;
                }
            }
            if (!name || !role) continue;
            if (seen.has(name)) continue;
            seen.add(name);
            const disabled = b.disabled || getComputedStyle(b).opacity < 0.5;
            out.push({ name, role, btnIdx: b.getAttribute('data-idx') || -1, disabled, b: bb, p: pp, bl, lo, hi });
        }
        // fix btnIdx (store index in the all-buttons list)
        const allBtns = document.querySelectorAll('button');
        out.forEach(c => {
            for (let i = 0; i < allBtns.length; i++) {
                if (allBtns[i].innerText && allBtns[i].innerText.includes(c.name)) { c.btnIdx = i; break; }
            }
        });
        return out;
    };
})();
"""


async def one_draft(page, num):
    log(f"=== DRAFT #{num} ===")
    await page.evaluate("""() => {
        const h = window.__h;
        h.picked = []; h.openSlots = [1,2,3,4,5,6,7,8,9,10,11];
        h.usage = {}; h.rerollTeam = null;
    }""")

    picks = []
    for spin in range(15):
        n_picks = len(picks)
        has_wk = any(p.get("role") == "WK" for p in picks)
        n_bowl70_now = sum(1 for p in picks if p.get("bl", 0) >= 70)
        n_bat86_now = sum(1 for p in picks if p.get("b", 0) >= 86)
        n_pow89_now = sum(1 for p in picks if p.get("p", 0) >= 89)
        n_bwl90_now = sum(1 for p in picks if p.get("bl", 0) >= 90)
        # Determine what role/stats we still need for tier-1 thresholds
        need = "bat"
        if not has_wk and n_picks >= 2:
            need = "wk"
        elif n_bowl70_now < 3 and n_picks >= 4:
            need = "bowl"

        result = await page.evaluate(f"() => window.__chooseTeam('{need}')")
        if not result:
            log(f"  spin {spin+1}: empty pool")
            break

        idx = result["idx"]
        pool_sz = result["poolSize"]
        log(f"  spin {spin+1}: {result['team']} (score={result['score']}, "
            f"idx={idx}/{pool_sz}, need={need})")

        await page.evaluate(f"""() => {{
            const h = window.__h;
            h.idx = {idx}; h.poolSz = {pool_sz}; h.overrideReady = true;
        }}""")

        spin_btn = page.locator("button").filter(has_text=re.compile("^SPIN$", re.I)).first
        if not await spin_btn.is_visible(timeout=3000):
            log(f"  no SPIN button")
            break
        await spin_btn.click(timeout=5000)
        await asyncio.sleep(2.5)

        # Read which team was selected: __lastSpinResult is captured by our injection
        try:
            selected_info = await page.evaluate("""() => {
                const r = window.__lastSpinResult;
                if (!r) return null;
                return {id: r.id, name: r.name, season: r.season};
            }""")
        except Exception:
            selected_info = None
        if selected_info:
            tid = selected_info["id"]
            try:
                await page.evaluate(f"() => {{ const h = window.__h; h.usage['{tid}'] = (h.usage['{tid}'] || 0) + 1; }}")
                usage = await page.evaluate(f"() => window.__h.usage['{tid}']")
                log(f"    tracked: {selected_info['name']} {selected_info['season']} (usage={usage})")
            except Exception:
                pass

        # Read cards from DOM
        cards = await page.evaluate("() => window.__readCards()")
        if not cards:
            log(f"    no cards found")
            continue

        # Choose best card — score by stats + role need for tier-1 thresholds
        # Tier-1: WK in XI, ≥3 BWL≥70, avg BAT(top7)≥86, avg POW(top7)≥89, avg BWL(bottom4)≥90
        scored = []
        for c in cards:
            if c.get("disabled"):
                continue
            s = c.get("b", 0) + c.get("p", 0) + c.get("bl", 0)  # base stat sum
            # Role need bonuses (big)
            if c["role"] == "WK" and not has_wk:
                s += 200
            elif c["role"] == "BOWLER" and c.get("bl", 0) >= 70 and n_bowl70_now < 3:
                s += 150
            elif c["role"] == "ALL-ROUNDER":
                s += 50
            # Stat quality bonuses
            if c.get("b", 0) >= 90: s += 30
            elif c.get("b", 0) >= 86: s += 15
            if c.get("p", 0) >= 90: s += 25
            elif c.get("p", 0) >= 88: s += 10
            if c.get("bl", 0) >= 90: s += 25
            elif c.get("bl", 0) >= 80: s += 10
            elif c.get("bl", 0) >= 70: s += 5
            scored.append((s, c))

        if not scored:
            log(f"    no enabled cards from {len(cards)} total")
            continue

        scored.sort(key=lambda x: x[0], reverse=True)
        best = scored[0][1]
        log(f"    -> {best['name']} ({best['role']})")

        btns = page.locator("button")
        await btns.nth(best["btnIdx"]).click(timeout=3000)
        await asyncio.sleep(1.0)

        # Handle position popup: digit buttons (1-11) in "Choose a batting position" dialog
        digits = await page.evaluate(r"""() => {
            const dlg = [...document.querySelectorAll('div')].find(d =>
                d.className && String(d.className).includes('fixed') &&
                /Choose a batting position/i.test(d.textContent||'') && d.querySelector('button'));
            const root = dlg || document;
            const out = [];
            for (const b of root.querySelectorAll('button')) {
                const t = (b.textContent || '').trim();
                if (/^\d{1,2}$/.test(t)) {
                    const st = b.getAttribute('style') || '';
                    const om = st.match(/opacity:\s*([\d.]+)/);
                    out.push({n: parseInt(t), dis: !!b.disabled, op: om ? parseFloat(om[1]) : 1});
                }
            }
            return out;
        }""")
        if digits:
            usable = [d["n"] for d in digits if not d["dis"] and d["op"] > 0.85]
            if usable:
                pos = usable[0]
                await page.evaluate(f"""() => {{
                    const dlgs = [...document.querySelectorAll('div')]
                        .filter(d => d.className && String(d.className).includes('fixed') &&
                                     /Choose a batting position/i.test(d.textContent||''));
                    const roots = dlgs.length ? dlgs : [document];
                    for (const root of roots)
                        for (const b of root.querySelectorAll('button'))
                            if ((b.textContent||'').trim() === '{pos}' && !b.disabled) {{ b.click(); return; }}
                }}""")
                await asyncio.sleep(0.5)

        picks.append({"name": best["name"], "role": best["role"], "b": best.get("b",0), "p": best.get("p",0), "bl": best.get("bl",0)})
        await page.evaluate(f"""() => {{
            const h = window.__h;
            h.picked.push({{name: '{best["name"]}'}});
            if (h.openSlots.length) h.openSlots.shift();
        }}""")

        if len(picks) >= 11:
            log(f"  All 11 picked!")
            break

    # Simulate
    log("  Simulating...")
    sim = page.locator("button").filter(has_text=re.compile("SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await sim.click(timeout=5000)
        await asyncio.sleep(2)
        skip = page.locator("button").filter(has_text=re.compile("SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000):
                await skip.click(timeout=3000)
        except Exception:
            pass
        await asyncio.sleep(3)

    ss = SHOTS_DIR / f"hack_d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)

    body = await page.inner_text("body")
    if "HISTORY REWRITTEN" in body:
        log(f"  >>> WIN! HISTORY REWRITTEN <<<")
        return True
    for kw in ["CHOKED", "HEARTBREAK", "OUTCLASSED", "UNPREPARED"]:
        if kw in body:
            log(f"  Result: {kw}")
            break
    score_m = re.search(r"(\d+/\d+)\s", body)
    if score_m:
        log(f"  Score: {score_m.group(1)}")

    again = page.locator("button").filter(has_text=re.compile("DRAFT AGAIN", re.I)).first
    try:
        if await again.is_visible(timeout=3000):
            await again.click(timeout=3000)
            await asyncio.sleep(2)
    except Exception:
        pass
    return False


async def main():
    log(f"spin_hack.py — HANDLE={HANDLE} MAX_DRAFTS={MAX_DRAFTS} STOP_ON_WIN={STOP_ON_WIN}")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx = await browser.new_context(viewport={"width": 480, "height": 1000}, device_scale_factor=2)
        page = await ctx.new_page()

        await setup_route_interception(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => localStorage.setItem('five-hundred-handle', '{HANDLE}')")

        ok_vo = await page.evaluate("() => !!window.__vo")
        ok_f6 = await page.evaluate("() => !!window.__f6")
        log(f"Capture: vo={'OK' if ok_vo else 'MISS'} f6={'OK' if ok_f6 else 'MISS'}")
        if not ok_vo:
            log("FATAL: cannot capture game internals")
            await browser.close()
            return
        log(f"Teams: {await page.evaluate('() => window.__vo.length')}")

        # Inject the full hack (PRNG + chooseTeam + readCards)
        seed = random.randint(1, 2**31 - 1)
        await page.evaluate(INJECT_HACK_JS.replace("SEED", str(seed)))
        log(f"Hack injected (seed={seed})")

        easy = page.locator("button").filter(has_text=re.compile("^EASY", re.I)).first
        await easy.click(timeout=3000)
        await asyncio.sleep(0.5)
        draft = page.locator("button").filter(has_text=re.compile("^DRAFT$", re.I)).first
        await draft.click(timeout=3000)
        await asyncio.sleep(2)
        log("Entered draft")

        wins = 0
        for i in range(1, MAX_DRAFTS + 1):
            won = await one_draft(page, i)
            if won:
                wins += 1
                if STOP_ON_WIN:
                    break

        log(f"=== DONE: {wins}/{MAX_DRAFTS} wins ===")
        await page.wait_for_timeout(3000)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
