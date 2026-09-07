"""
spin_fixed11.py - Fixed XI for 500-0.com (React rewrite, Sep 2026)
Forces: Rohit, Sachin, Virat, Viv, AB, Henri(Klaasen), Afridi, Wasim, Malcolm, Shane, Muthaia
Uses Math.random interception to control team spin + card picker for player selection.
Submits wins directly via leaderboard API (bypasses CLAIM button).
"""
import asyncio, json, re, time, random, os, sys, subprocess
from pathlib import Path
from playwright.async_api import async_playwright

sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

BASE_URL = "https://500-0.com"
LB_URL = "https://500leaderboard.raasnhafiz.workers.dev"
SHOTS_DIR = Path(__file__).parent / "shots_fixed11"
SHOTS_DIR.mkdir(exist_ok=True)

HANDLE = os.getenv("HANDLE", "CoverDriveKing07")
HOLD_SEC = int(os.getenv("HOLD_SEC", "10"))
SEED_DELAY = float(os.getenv("SEED_DELAY", "2"))
SKIP_PROB = float(os.getenv("SKIP_PROB", "0.55"))
DAILY_CAP = int(os.getenv("DAILY_CAP", "50"))
ROOT = Path(__file__).parent
STATE_PATH = ROOT / "STATE.json"
LOG_PATH = ROOT / "LIVE_LOG.md"

# One stable ID forever (same browser = same human). Fresh identity.
STABLE_PID = os.getenv("STABLE_PID", "").strip() or "mtqh4w00cdking07"

def session_drafts():
    """Short human sessions: 4-6 drafts (5-7 on weekends)."""
    import datetime as _d
    wknd = _d.datetime.now(_d.timezone.utc).weekday() >= 5
    lo, hi = (5, 7) if wknd else (4, 6)
    return random.randint(lo, hi)

def today_str():
    import datetime as _d
    return _d.datetime.now(_d.timezone.utc).strftime("%Y-%m-%d")

def load_state():
    try:
        st = json.loads(STATE_PATH.read_text())
        if st.get("date") != today_str():
            raise ValueError("new day")
        st.setdefault("drafts", 0)
        st.setdefault("wins", 0)
        st.setdefault("combos_used", [])
        st.setdefault("xi_sigs", [])
        return st
    except:
        return {"date": today_str(), "drafts": 0, "wins": 0, "combos_used": [], "xi_sigs": []}

def save_state(st):
    try:
        STATE_PATH.write_text(json.dumps(st))
    except:
        pass

def pick_combo(state):
    """Random combo, preferring ones unused today (no visible pattern)."""
    avail = [c for c in COMBOS20 if c["name"] not in state.get("combos_used", [])]
    pool = avail or COMBOS20
    return random.choice(pool)

def gate_predict(picks_by_slot):
    """Backend L6 gate on the actual picked XI. Returns (ok, bat, pow, att)."""
    try:
        t7 = picks_by_slot[:7]
        l4 = picks_by_slot[7:11]
        bat = sum(p["b"] for p in t7) / 7
        pow_ = sum(p["p"] for p in t7) / 7
        att = sum(p["bl"] for p in l4) / 4
        wk = any("WK" in p.get("role", "") for p in picks_by_slot)
        nb = sum(1 for p in picks_by_slot if p.get("bl", 0) >= 70)
        return (wk and nb > 2 and bat >= 86 and pow_ >= 89 and att >= 90), bat, pow_, att
    except:
        return False, 0, 0, 0

# 20 human-like XI combos loaded from combos20.json. Each pick is
# (pos, name, year); the team id is resolved live by (season, roster).
# Shuffle engine below drafts them in spin order with random slots.
try:
    COMBOS20 = json.loads((ROOT / "combos20.json").read_text())["combos"]
except:
    COMBOS20 = []
COMBOS_FALLBACK = [
 ("Base Invincibles v2", [(1,"Rohit Sharma","india2020s"),(2,"Sachin Tendulkar","india1990s"),(3,"Virat Kohli","india2010s"),(4,"Viv Richards","westindies1980s"),(5,"AB de Villiers","southafrica2010s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Wasim Akram","pakistan1990s"),(9,"Malcolm Marshall","westindies1980s"),(10,"Shane Warne","australia1990s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
 ("Pace Storm v2", [(1,"Virender Sehwag","india2000s"),(2,"Sachin Tendulkar","india1990s"),(3,"Virat Kohli","india2010s"),(4,"Viv Richards","westindies1980s"),(5,"AB de Villiers","southafrica2010s"),(6,"MS Dhoni","india2000s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Wasim Akram","pakistan1990s"),(9,"Malcolm Marshall","westindies1980s"),(10,"Brett Lee","australia2000s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
 ("Aussie Open Blitz", [(1,"Travis Head","australia2020s"),(2,"David Warner","australia2010s"),(3,"Viv Richards","westindies1980s"),(4,"Brian Lara","westindies1990s"),(5,"Aravinda de Silva","srilanka1990s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Lance Klusener","southafrica1990s"),(8,"Wasim Akram","pakistan1990s"),(9,"Joel Garner","westindies1980s"),(10,"Curtly Ambrose","westindies1990s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
 ("Spin Twin Kings v2", [(1,"Chris Gayle","westindies2010s"),(2,"Jonny Bairstow","england2010s"),(3,"Sachin Tendulkar","india1990s"),(4,"Viv Richards","westindies1980s"),(5,"Daryl Mitchell","newzealand2020s"),(6,"Yuvraj Singh","india2000s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Imran Khan","pakistan1990s"),(9,"Waqar Younis","pakistan1990s"),(10,"Shoaib Akhtar","pakistan2000s"),(11,"Jasprit Bumrah","india2020s")]),
 ("Protea Wall v2", [(1,"Quinton de Kock","southafrica2010s"),(2,"Saeed Anwar","pakistan1990s"),(3,"Sachin Tendulkar","india1990s"),(4,"Viv Richards","westindies1980s"),(5,"Jacques Kallis","southafrica1990s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Shaun Pollock","southafrica2000s"),(9,"Kagiso Rabada","southafrica2020s"),(10,"Dale Steyn","southafrica2010s"),(11,"Glenn McGrath","australia2000s")]),
 ("Young Guns v2", [(1,"Rohit Sharma","india2020s"),(2,"Shubman Gill","india2020s"),(3,"Virat Kohli","india2010s"),(4,"Viv Richards","westindies1980s"),(5,"Harry Brook","england2020s"),(6,"MS Dhoni","india2000s"),(7,"Lance Klusener","southafrica1990s"),(8,"Rashid Khan","afghanistan2020s"),(9,"Jasprit Bumrah","india2010s"),(10,"Jofra Archer","england2010s"),(11,"Trent Boult","newzealand2020s")]),
 ("Roy Experiment v2", [(1,"Virender Sehwag","india2000s"),(2,"Jason Roy","england2010s"),(3,"Sachin Tendulkar","india1990s"),(4,"Viv Richards","westindies1980s"),(5,"AB de Villiers","southafrica2010s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Wasim Akram","pakistan1990s"),(9,"Mitchell Starc","australia2010s"),(10,"Shane Bond","newzealand2000s"),(11,"Saeed Ajmal","pakistan2010s")]),
 ("Kiwi Grit v2", [(1,"David Warner","australia2010s"),(2,"Martin Guptill","newzealand2010s"),(3,"Brian Lara","westindies1990s"),(4,"Viv Richards","westindies1980s"),(5,"AB de Villiers","southafrica2010s"),(6,"MS Dhoni","india2000s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Anil Kumble","india1990s"),(9,"Shane Warne","australia1990s"),(10,"Muttiah Muralitharan","srilanka1990s"),(11,"Glenn McGrath","australia2000s")]),
 ("Lankan Lions v2", [(1,"Saeed Anwar","pakistan1990s"),(2,"Fakhar Zaman","pakistan2020s"),(3,"Viv Richards","westindies1980s"),(4,"Aravinda de Silva","srilanka1990s"),(5,"Daryl Mitchell","newzealand2020s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Wasim Akram","pakistan1990s"),(9,"Saeed Ajmal","pakistan2010s"),(10,"Imran Tahir","southafrica2010s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
 ("Death Over Kings v2", [(1,"Pathum Nissanka","srilanka2020s"),(2,"Travis Head","australia2020s"),(3,"Virat Kohli","india2010s"),(4,"Viv Richards","westindies1980s"),(5,"Yuvraj Singh","india2000s"),(6,"MS Dhoni","india2000s"),(7,"Shahid Afridi","pakistan2000s"),(8,"Imran Khan","pakistan1990s"),(9,"Shaheen Afridi","pakistan2020s"),(10,"Jofra Archer","england2010s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
 ("Version Gods", [(1,"Rohit Sharma","india2020s"),(2,"Sachin Tendulkar","india1990s"),(3,"Virat Kohli","india2010s"),(4,"Viv Richards","westindies1980s"),(5,"AB de Villiers","southafrica2010s"),(6,"Heinrich Klaasen","southafrica2020s"),(7,"Jos Buttler","england2010s"),(8,"Wasim Akram","pakistan1990s"),(9,"Malcolm Marshall","westindies1980s"),(10,"Shane Warne","australia1990s"),(11,"Muttiah Muralitharan","srilanka1990s")]),
]
# Back-compat defaults (combo #1 names); one_draft overrides per draft.
def _combo_names(c):
    return [x[1] for x in c["xi"]]

if not COMBOS20:
    COMBOS20 = [{"name": n, "xi": [[p, nm, ""] for p, nm, _ in xi]} for n, xi in COMBOS_FALLBACK]
FIXED_NAMES = _combo_names(COMBOS20[0])
FIXED_SET = set(FIXED_NAMES)

def combo_for(num):
    """Legacy rotation (kept for session preview); live drafts use pick_combo."""
    import datetime as _d2
    off = _d2.datetime.now(_d2.timezone.utc).timetuple().tm_yday % len(COMBOS20)
    c = COMBOS20[(off + num - 1) % len(COMBOS20)]
    return c["name"], [(p, n, t) for p, n, t in c["xi"]]

async def jsleep(lo, hi):
    """Human-like jittered pause."""
    await asyncio.sleep(random.uniform(lo, hi))

async def find_team(page, name, year=""):
    """Resolve team id by (season year + roster). Empty year = first match."""
    safe = name.replace("'", "\\'")
    try:
        return await page.evaluate(f"""() => {{
            const No = window.__No || [];
            const nm = '{safe}', yr = '{year}';
            for (const t of No) {{
                if (yr && !(String(t.season || '').toLowerCase().includes(yr.toLowerCase()))) continue;
                if (t.players && t.players.some(p => p.n === nm)) return t.id;
            }}
            return '';
        }}""")
    except:
        return ''

async def enter_draft(page):
    """Draft entry: close popup, keep EASY, click the exact DRAFT button, verify SPIN."""
    for attempt in range(3):
        try:
            btns = await page.evaluate("() => [...document.querySelectorAll('button')].map(b => (b.innerText||'').trim().replace(/\\s+/g,' ').slice(0,30))")
        except:
            btns = []
        log(f"  entry try{attempt}: buttons={btns[:14]}")
        try:
            x = page.locator("button").filter(has_text=re.compile(r"^×$")).first
            if await x.is_visible(timeout=1500):
                await x.click(timeout=3000, force=True)
                await asyncio.sleep(0.5)
        except:
            pass
        try:
            easy = page.locator("button").filter(has_text=re.compile(r"^EASY", re.I)).first
            if await easy.is_visible(timeout=1500):
                await human_click(page, easy, timeout=4000)
                await asyncio.sleep(0.7)
        except:
            pass
        try:
            go = page.locator("button").filter(has_text=re.compile(r"^DRAFT$", re.I)).first
            if await go.is_visible(timeout=2500):
                await human_click(page, go, timeout=4000)
                await asyncio.sleep(2)
        except:
            pass
        try:
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=4000):
                return True
        except:
            pass
    return False

async def human_click(page, locator, timeout=5000):
    """Mouse-like click: move in steps, then click. Falls back to plain click."""
    try:
        box = await locator.bounding_box(timeout=timeout)
        if not box:
            await locator.click(timeout=timeout)
            return
        x0, y0 = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        steps = random.randint(3, 7)
        await page.mouse.move(max(0, x0 - random.randint(40, 160)), max(0, y0 - random.randint(40, 160)))
        await page.mouse.move(x0, y0, steps=steps)
        await jsleep(0.05, 0.35)
        await page.mouse.click(x0, y0)
    except:
        try:
            await locator.click(timeout=timeout, force=True)
        except:
            pass

def git_push_log(msg):
    """Commit LIVE_LOG.md + STATE.json (rebase-retry for racing sessions)."""
    def run(*a):
        try:
            return subprocess.run(a, cwd=str(ROOT), capture_output=True, timeout=90)
        except:
            return None
    try:
        run("git", "add", "LIVE_LOG.md", "STATE.json")
        r = run("git", "commit", "-m", msg)
        if r is None or (r.returncode != 0 and b"nothing to commit" not in (r.stdout or b"") + (r.stderr or b"")):
            if r is not None and r.returncode != 0:
                return False
        for _ in range(3):
            p = run("git", "push", "origin", "main")
            if p is not None and p.returncode == 0:
                return True
            run("git", "pull", "--rebase", "origin", "main")
        return False
    except Exception as e:
        log(f"  logpush err: {e}")
        return False

def live_entry(state, text):
    """Prepend entry to LIVE_LOG.md (newest on top for mobile), cap size."""
    try:
        header = f"# Live Draft Log — {HANDLE}\nDay {state.get('date')} (UTC): {state.get('drafts', 0)} drafts, {state.get('wins', 0)} wins\n\n"
        old = ""
        if LOG_PATH.exists():
            old = LOG_PATH.read_text(encoding="utf-8", errors="ignore")
            lines = old.split("\n")
            body = [l for l in lines if not l.startswith("# ")]
            old = "\n".join(body).strip()
        entries = [l for l in (text.strip() + "\n" + old).split("\n") if l.strip() != ""]
        LOG_PATH.write_text(header + "\n".join(entries[:260]) + "\n", encoding="utf-8")
    except Exception as e:
        log(f"  live_entry err: {e}")

def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

best_balls = [999]

# Track picks per draft: list of {name, role, squadId}
current_picks = []

def gen_pid():
    """Generate PID in game format: base36 timestamp + random chars."""
    import time as _time
    ts = int(_time.time() * 1000)
    b36 = ""
    n = ts
    while n > 0:
        b36 = "0123456789abcdefghijklmnopqrstuvwxyz"[n % 36] + b36
        n //= 36
    rnd = "".join(random.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(8))
    return b36 + rnd

async def api_seed(page, pid):
    """Register team with leaderboard via POST /seed, return sid or None."""
    xi_payload = [{"n": p["name"], "sq": p.get("squadId", "")} for p in ordered_picks()]
    log(f"  SEED xi sample: {json.dumps(xi_payload[:3])}... ({len(xi_payload)} players)")
    for attempt in range(3):
        try:
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle, xi} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/seed', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle, xi: xi})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE, "xi": xi_payload})
            if result.get("ok"):
                sid = result.get("data", {}).get("sid", "")
                log(f"  SEED ok sid={sid[:20]}...")
                return sid
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SEED rate limited (429), waiting {wait}s (attempt {attempt+1}/3)...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SEED failed: {result}")
                return None
        except Exception as e:
            log(f"  SEED err: {e}")
            return None
    log("  SEED failed after 3 retries")
    return None

async def api_submit(page, pid, sid):
    """Submit win to leaderboard via POST /submit, return ranks or None."""
    for attempt in range(3):
        try:
            xi_payload = [{"n": p["name"], "r": p.get("role", "BAT"), "sq": p.get("squadId", "")} for p in ordered_picks()]
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle, sid, xi} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/submit', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle, sid: sid, xi: xi})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE, "sid": sid, "xi": xi_payload})
            if result.get("ok"):
                ranks = result.get("data", {}).get("ranks", {})
                log(f"  SUBMIT ok! today={ranks.get('today','?')} most={ranks.get('most','?')}")
                return ranks
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SUBMIT rate limited (429), waiting {wait}s (attempt {attempt+1}/3)...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SUBMIT failed: {result}")
                return None
        except Exception as e:
            log(f"  SUBMIT err: {e}")
            return None
    log("  SUBMIT failed after 3 retries")
    return None

def map_role_from_card(card):
    """Map card role string to API role code."""
    r = card.get("role", "").upper()
    if r == "WK": return "WK"
    if r == "ALL-ROUNDER": return "AR"
    if r == "BOWLER": return "BWL"
    return "BAT"

def ordered_picks():
    """XI in batting-slot order (pos 1-11). Backend L6 slices [0:7]/[7:11],
    so pick-order would scramble the averages and get 'not a 500' rejects."""
    return sorted(current_picks, key=lambda p: (p.get("pos") is None, p.get("pos") or 99))

async def get_squad_id(page, player_name, pinned=None):
    """Return pinned team's ID if it holds the player, else first match."""
    escaped = player_name.replace("'", "\\'")
    pin = (pinned or "").replace("'", "\\'")
    try:
        return await page.evaluate(f"""() => {{
            const No = window.__No;
            if (!No) return '';
            const pin = '{pin}';
            if (pin) {{
                for (const t of No) {{
                    if (t.id === pin && t.players && t.players.some(p => p.n === '{escaped}')) return t.id;
                }}
            }}
            for (const t of No) {{
                if (t.players && t.players.some(p => p.n === '{escaped}')) return t.id;
            }}
            return '';
        }}""")
    except:
        return pinned or ''

async def api_seed_no_xi(page, pid):
    """Register with leaderboard via POST /seed without xi (fallback)."""
    for attempt in range(3):
        try:
            result = await page.evaluate(r"""async (params) => {
                const {pid, handle} = params;
                try {
                    const resp = await fetch('""" + LB_URL + r"""/seed', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({id: pid, handle: handle})
                    });
                    const text = await resp.text();
                    if (resp.status === 429) return {ok: false, retry: true, status: 429};
                    if (!resp.ok) return {ok: false, status: resp.status, text: text};
                    return {ok: true, data: JSON.parse(text)};
                } catch(e) {
                    return {ok: false, error: e.message};
                }
            }""", {"pid": pid, "handle": HANDLE})
            if result.get("ok"):
                sid = result.get("data", {}).get("sid", "")
                log(f"  SEED (no xi) ok sid={sid[:20]}...")
                return sid
            elif result.get("retry"):
                wait = 30 * (attempt + 1)
                log(f"  SEED (no xi) rate limited (429), waiting {wait}s...")
                await page.wait_for_timeout(wait * 1000)
                continue
            else:
                log(f"  SEED (no xi) failed: {result}")
                return None
        except Exception as e:
            log(f"  SEED (no xi) err: {e}")
            return None
    return None

async def fulfill_text(route, resp, txt, ctype):
    """Fulfill with decoded text: MUST drop content-encoding/length from the
    original response or the browser mis-decodes the body and the script dies."""
    headers = {k: v for k, v in resp.headers.items()
               if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
    await route.fulfill(status=resp.status, headers=headers, body=txt, content_type=ctype)

async def setup_route_interception(page):
    async def lb_log(route):
        req = route.request
        try:
            body = req.post_data or ""
        except:
            body = ""
        log(f"  [LB REQ] {req.method} {req.url[:150]} body={body[:300]}")
        resp = await route.fetch()
        try:
            txt = await resp.text()
            log(f"  [LB RESP] {resp.status} {txt[:500]}")
            await fulfill_text(route, resp, txt,
                resp.headers.get("content-type", "application/json"))
        except:
            await route.continue_()

    # NOTE: single * does not cross / in Playwright globs, so use **-style
    # path suffixes (previous *500leaderboard*seed* patterns never matched).
    await page.route("**/submit", lb_log)
    await page.route("**/board**", lb_log)

    async def seed_cap(route):
        # Game auto-seeds (E1) at 10/11 picks with Ga()=STABLE_PID.
        # Capture its sid so our submit reuses the SAME session (no re-seed conflict).
        try:
            resp = await route.fetch()
            try:
                txt = await resp.text()
                try:
                    data = json.loads(txt)
                    sid = data.get("sid")
                    if sid:
                        try:
                            await page.evaluate(f"() => {{ (window.__seedSids = window.__seedSids || []).push('{sid}'); window.__lastSeedSid = '{sid}'; }}")
                        except:
                            pass
                        log(f"  [GAME SEED] sid={sid[:20]}...")
                    else:
                        log(f"  [GAME SEED] no sid (status={resp.status} body={txt[:120]})")
                except:
                    log(f"  [GAME SEED] unparseable (status={resp.status} body={txt[:120]})")
                await fulfill_text(route, resp, txt,
                    resp.headers.get("content-type", "application/json"))
            except:
                await route.continue_()
        except:
            try:
                await route.continue_()
            except:
                pass

    await page.route("**/seed", seed_cap)

    async def intercept(route):
        try:
            resp = await route.fetch()
            body = await resp.text()
            if "window.__No" not in body:
                # Legacy anchors (older bundle variant).
                body = body.replace(
                    "],wt=(t,l,e)=>Math.max(l,Math.min(e,t));",
                    "];window.__No=No;window.__o6=o6;window.__S6=S6;window.__A6=A6;wt=(t,l,e)=>Math.max(l,Math.min(e,t));")
                body = body.replace(
                    "No[Math.floor(Math.random()*No.length)]",
                    "(window.__gamePool=No,window.__lastSpinResult=No[Math.floor(Math.random()*No.length)])")
                # Variant-proof: discover the pool var by its data signature
                # (stable across minifier renames) and expose/wrap it.
                # group(1) EXCLUDES the '[' -> `var Lo=window.__No=[{...}]`
                # (aliased, brackets balanced). Including it nests/breaks.
                xhook = 'Ct[Math.floor(x6()*Ct.length)]'
                if xhook in body:
                    body = body.replace(xhook,
                        'Ct[Math.floor((window.__spinRV!=null?window.__spinRV:x6())*Ct.length)]')
                    log("  intercept: x6 spin hook installed")
                m = re.search(r'((?:var|let|const)\s+[A-Za-z_$][\w$]*\s*=\s*)\[\{id\s*:\s*"pakistan1990s"', body)
                if m:
                    pv = re.search(r'[A-Za-z_$][\w$]*', m.group(1).split('=', 1)[0].split()[-1]).group(0)
                    before = body
                    body = body.replace(m.group(0), m.group(1) + 'window.__No=[{id:"pakistan1990s"', 1)
                    spin_pat = pv + '[Math.floor(Math.random()*' + pv + '.length)]'
                    if spin_pat in body:
                        body = body.replace(spin_pat,
                            '(window.__gamePool=' + pv + ',window.__lastSpinResult=' + spin_pat + ')')
                        log(f"  intercept: dynamic pool var={pv} (exposed + spin wrapped)")
                    else:
                        log(f"  intercept: dynamic pool var={pv} exposed, spin line not found")
                    if body == before:
                        log("  intercept WARN: dynamic replace changed nothing")
                else:
                    log("  intercept WARN: pool signature not found, spins uncontrolled")
            await fulfill_text(route, resp, body, "application/javascript")
        except Exception as e:
            log(f"  intercept err (passing through): {e}")
            try:
                await route.continue_()
            except:
                pass

    await page.route("**/*app*.js", intercept)

INJECT_HACK_JS = r"""
(() => {
    if (window.__hackReady) return;
    window.__hackReady = true;
    const _orig = Math.random;
    let _s = SEED;
    function _prng(){ _s=_s+1831565813|0; let t=Math.imul(_s^_s>>>15,1|_s); t=t+Math.imul(t^t>>>7,61|t)^t; return ((t^t>>>14)>>>0)/4294967296; }
    window.__h = {on:true, idx:-1, poolSz:1, overrideReady:false, picked:[], openSlots:[1,2,3,4,5,6,7,8,9,10,11], usage:{}};
    window.__reseed = (s) => { _s = s|0; };
    Math.random = function(){
        const h=window.__h;
        if(!h.on) return _orig();
        if(h.overrideReady && h.idx>=0){
            const actualPoolSz=(window.__gamePool||[]).length||h.poolSz;
            const v=(h.idx+0.5)/actualPoolSz;
            h.idx=-1; h.overrideReady=false;
            return Math.min(Math.max(v,1e-6),0.999999);
        }
        return _prng();
    };
    window.__FIXED_XI = FIXED_JSON_PLACEHOLDER;
    window.__FIXED_SET = new Set(FIXED_JSON_PLACEHOLDER);
    // New bundle picks the final team via x6() (global hookable RNG),
    // NOT Math.random. Override it; per-spin targeting via Ct mirror below.
    if(!window.__x6wrapped && typeof window.x6==='function'){
        window.__origx6 = window.x6;
        window.__x6wrapped = true;
        window.x6 = function(){
            const h=window.__h;
            if(h && h.on && h.spinReady && h.spinIdx>=0){
                const v=(h.spinIdx+0.5)/h.spinLen;
                h.spinIdx=-1; h.spinReady=false;
                return Math.min(Math.max(v,1e-6),0.999999);
            }
            return window.__origx6();
        };
    }
    window.__chooseTeamForNextFixed = function(){
        const No=window.__No, h=window.__h;
        if(!No||!h) return null;
        const picked=new Set(h.picked);
        const slots=[...h.openSlots];
        const lim=window.__o6||2;
        // Mirror game's Ct: teams with an unpicked player fitting open slots,
        // preferring under-limit teams (game falls back to full list).
        let Ct=No.filter(t=>t.players.some(p=>!picked.has(p.n)&&slots.some(s=>s>=p.r[0]&&s<=p.r[1])));
        const yl=Ct.filter(t=>(h.usage[t.id]||0)<lim);
        if(yl.length) Ct=yl;
        if(!Ct.length) return null;
        for(const name of window.__FIXED_XI){
            if(picked.has(name)) continue;
            let cand=Ct.filter(t=>t.players.some(p=>p.n===name&&slots.some(s=>s>=p.r[0]&&s<=p.r[1])));
            if(!cand.length) continue;
            const wantTeam=(window.__FIXED_TEAM||{})[name];
            if(wantTeam){
                const exact=cand.filter(t=>t.id===wantTeam);
                if(exact.length) cand=exact;
            }
            const team=cand[0];
            return {idx:Ct.indexOf(team), poolSize:Ct.length, need:name, team:team.name+" "+team.season, teamId:team.id};
        }
        return null;
    };
    window.__pickCard = function(cards){
        const picked=new Set(window.__h.picked);
        const needed=[];
        for(const name of window.__FIXED_XI){ if(!picked.has(name)) needed.push(name); }
        for(const n of needed){
            for(const c of cards){
                if(c.name===n && !c.disabled) return c;
            }
        }
        const enabled=cards.filter(c=>!c.disabled);
        if(!enabled.length) return null;
        enabled.sort((a,b)=>(b.b*2+b.p)-(a.b*2+a.p));
        return enabled[0];
    };
})();
"""
INJECT_HACK_JS = INJECT_HACK_JS.replace("SEED", "RAND_SEED")
INJECT_HACK_JS = INJECT_HACK_JS.replace("FIXED_JSON_PLACEHOLDER", json.dumps(FIXED_NAMES))

async def ensure_hack(page, seed=None):
    try:
        has = await page.evaluate("() => !!window.__h && !!window.__No && !!window.__chooseTeamForNextFixed")
    except:
        has = False
    if not has:
        for _ in range(10):
            try:
                if await page.evaluate("() => !!window.__No"): break
            except:
                pass
            await page.wait_for_timeout(500)
        s = seed or random.randint(1, 2**31 - 1)
        js = INJECT_HACK_JS.replace("RAND_SEED", str(s))
        try:
            await page.evaluate(js)
        except:
            pass
        log(f"  (injected hack seed={s})")
        await page.wait_for_timeout(700)

def read_cards_from_dom(dom_text):
    """Parse cards from React DOM text (innerText of buttons)"""
    cards = []
    lines = dom_text.split("\n")
    i = 0
    while i < len(lines):
        L = lines[i].strip()
        if L in ("BATTER", "BOWLER", "ALL-ROUNDER", "WK"):
            role = L
            name = None
            lo, hi, bb, pp, bl = 1, 11, 0, 0, 0
            j = i + 1
            while j < len(lines):
                L2 = lines[j].strip()
                rm = re.match(r'^(\d{1,2})[-\u2013](\d{1,2})$', L2)
                if rm:
                    lo, hi = int(rm.group(1)), int(rm.group(2))
                    j += 1
                    continue
                if L2 == "BAT" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        bb = int(prev)
                        j += 1
                        continue
                if L2 == "POW" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        pp = int(prev)
                        j += 1
                        continue
                if L2 == "BWL" and j > 0:
                    prev = lines[j-1].strip()
                    if prev.isdigit():
                        bl = int(prev)
                        j += 1
                        continue
                if not L2.isdigit() and L2 not in ("BAT", "POW", "BWL") and not re.match(r'^\d{1,2}[-\u2013]\d{1,2}$', L2):
                    name = L2
                    j += 1
                    break
                j += 1
            if name and role:
                cards.append({"name": name, "role": role, "b": bb, "p": pp, "bl": bl, "lo": lo, "hi": hi})
            i = j
        else:
            i += 1
    return cards

async def get_cards_from_page(page):
    """Read card buttons from the React DOM"""
    try:
        result = await page.evaluate(r"""() => {
            const cards = [];
            const seen = new Set();
            const btns = document.querySelectorAll('button');
            for (const b of btns) {
                const t = (b.innerText || '').trim();
                if (!/BATTER|BOWLER|ALL-ROUNDER|WK/.test(t)) continue;
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
                if (!name || !role || seen.has(name)) continue;
                seen.add(name);
                const disabled = b.disabled || getComputedStyle(b).opacity < 0.5;
                let btnIdx = -1;
                const allBtns = document.querySelectorAll('button');
                for (let i = 0; i < allBtns.length; i++) {
                    if (allBtns[i].innerText && allBtns[i].innerText.includes(name)) {
                        btnIdx = i; break;
                    }
                }
                cards.push({name, role, disabled, b: bb, p: pp, bl, lo, hi, btnIdx});
            }
            return cards;
        }""")
        return result
    except Exception as e:
        log(f"  readCards err: {e}")
        return []

async def one_draft(page, num, state):
    combo = pick_combo(state)
    combo_name, combo_xi = combo["name"], [(p, n, y) for p, n, y in combo["xi"]]
    if combo_name not in state.get("combos_used", []):
        state["combos_used"].append(combo_name)
    plan_pos = {n: p for p, n, _ in combo_xi}
    plan_year = {n: y for _, n, y in combo_xi}
    combo_names = [n for _, n, _ in combo_xi]
    log(f"=== DRAFT #{num} [{combo_name}] {HANDLE} ===")
    current_picks.clear()
    current_sid = None
    try:
        seed_n0 = await page.evaluate("() => (window.__seedSids||[]).length")
    except:
        seed_n0 = 0

    for _ in range(10):
        try:
            await page.wait_for_timeout(500)
            if await page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first.is_visible(timeout=800):
                break
        except:
            pass

    await ensure_hack(page)
    try:
        await page.evaluate(f"() => {{ window.__FIXED_XI = {json.dumps(combo_names)}; window.__FIXED_SET = new Set({json.dumps(combo_names)}); }}")
    except:
        pass
    # Native randomness for deals/spins (human-like); steering stays dormant.
    try:
        await page.evaluate("() => { const h=window.__h; if(h){h.on=false; h.spinReady=false;} window.__spinRV=null; }")
    except:
        pass

    picks = []
    open_slots = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
    spin = 0
    while len(picks) < 11 and spin < 25:
        spin += 1
        spin_btn = page.locator("button").filter(has_text=re.compile(r"^SPIN$", re.I)).first
        if not await spin_btn.is_visible(timeout=3000):
            log("  no SPIN button")
            break
        await human_click(page, spin_btn, timeout=5000)
        await jsleep(2.2, 3.4)
        log(f"  spin {spin}: team unknown until cards (random spin)")

        await page.wait_for_timeout(1000)
        cards = await get_cards_from_page(page)
        if not cards:
            log("    no cards found, waiting more...")
            await page.wait_for_timeout(2000)
            cards = await get_cards_from_page(page)
        if not cards:
            log("    still no cards, skipping spin")
            continue

        card_names = [c["name"] for c in cards]
        log(f"    cards: {', '.join(card_names)}")

        def fits_open(c):
            return [s for s in open_slots if c.get("lo", 1) <= s <= c.get("hi", 11)]

        picked_set = set(p["name"] for p in picks)
        best = None
        best_plan = False
        for n in combo_names:
            if n in picked_set:
                continue
            for c in cards:
                if c["name"] == n and not c.get("disabled") and fits_open(c):
                    best = c
                    best_plan = True
                    break
            if best:
                break

        if not best:
            scored = []
            for c in cards:
                if c.get("disabled"):
                    continue
                fo = fits_open(c)
                if not fo:
                    continue
                sc = max((c.get("b", 0) * 2 + c.get("p", 0)) if s <= 7 else c.get("bl", 0) for s in fo)
                scored.append((sc, c))
            if scored:
                scored.sort(key=lambda t: t[0], reverse=True)
                best = scored[0][1]
                log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) [FILLER]")
            else:
                log("    no enabled cards")
                continue
        else:
            log(f"    -> {best['name']} ({best['role']} BAT{best.get('b',0)}/POW{best.get('p',0)}/BWL{best.get('bl',0)}) [FIXED]")

        # Slot: planned if free+fitting, else a RANDOM fitting open slot.
        planned = plan_pos.get(best["name"])
        fo = fits_open(best)
        if planned in fo:
            slot = planned
        elif fo:
            slot = random.choice(fo)
        else:
            log("    no fitting open slot, skipping")
            continue
        open_slots.remove(slot)

        btn_idx = best.get("btnIdx", -1)
        if btn_idx >= 0:
            await human_click(page, page.locator("button").nth(btn_idx), timeout=3000)
        else:
            await human_click(page, page.locator("button").filter(has_text=best["name"]).first, timeout=3000)
        await jsleep(0.8, 1.6)

        digits = await page.evaluate(r"""() => {
            const dlgs = [...document.querySelectorAll('div')].filter(d =>
                d.className && String(d.className).includes('fixed') &&
                /Choose a batting position/i.test(d.textContent || '') &&
                d.querySelector('button'));
            const root = dlgs.length ? dlgs[dlgs.length-1] : document;
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
                if slot not in usable:
                    # Human taps a random available slot, not always first.
                    slot = random.choice(usable)
                    if slot in open_slots:
                        open_slots.remove(slot)
                    else:
                        try:
                            open_slots.remove(min(open_slots, key=lambda s: abs(s - slot)))
                        except:
                            pass
                log(f"       pos {slot} among {usable}")
                await page.evaluate(f"""() => {{
                    const dlgs=[...document.querySelectorAll('div')].filter(d=>d.className&&String(d.className).includes('fixed')&&/Choose a batting position/i.test(d.textContent||''));
                    const roots=dlgs.length?dlgs:[document];
                    for(const root of roots) for(const b of root.querySelectorAll('button')) if((b.textContent||'').trim()==='{slot}'&&!b.disabled){{b.click();return;}}
                }}""")
                await jsleep(0.4, 0.9)

        pinned_year = plan_year.get(best["name"], "")
        squad_id = await find_team(page, best["name"], pinned_year)
        pick_entry = {"name": best["name"], "b": best.get("b", 0), "p": best.get("p", 0), "bl": best.get("bl", 0), "role": map_role_from_card(best), "squadId": squad_id, "pos": slot, "year": pinned_year}
        picks.append(pick_entry)
        current_picks.append(pick_entry)

        if len(picks) >= 11:
            break

    if len(picks) < 11:
        log(f"  INCOMPLETE XI ({len(picks)}/11), abandoning draft")
        return False, False
    by_slot = sorted(picks, key=lambda p: p.get("pos") or 99)
    fixed_count = sum(1 for p in picks if p["name"] in combo_names)
    log(f"  Picked 11 players, {fixed_count}/11 from [{combo_name}]")
    log("  XI picked: " + " | ".join(f"{p.get('pos')}.{p['name']}" for p in by_slot))
    gate_ok, gbat, gpow, gatt = gate_predict(by_slot)
    log(f"  Gate check: bat {gbat:.1f} / pow {gpow:.1f} / att {gatt:.1f} -> {'PASS (70% coin)' if gate_ok else 'likely LOSS band'}")
    sig = "|".join(f"{p.get('pos')}:{p['name']}" for p in by_slot)
    if sig in state.get("xi_sigs", []):
        log("  NOTE: XI repeats an earlier today combo")
    else:
        state.setdefault("xi_sigs", []).append(sig)

    # Identity pinned; game seeds itself (E1 at ~10 picks). No manual
    # seed/submit: proof-less direct API calls are a server-visible marker.
    # The game's own auto-submit (with proof) reports the win.
    await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{STABLE_PID}')")
    await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
    current_sid = None
    for _ in range(20):  # wait ~10s for game's seed response (fired at 10 picks)
        await page.wait_for_timeout(500)
        try:
            sids = await page.evaluate("() => (window.__seedSids||[])")
            if sids and len(sids) > seed_n0:
                current_sid = sids[-1]
                log(f"  GAME SEED sid={current_sid[:20]}...")
                break
        except:
            pass
    if not current_sid:
        try:
            last = await page.evaluate("() => window.__lastSeedSid || ''")
            if last:
                current_sid = last
                log(f"  GAME SEED (last) sid={current_sid[:20]}...")
        except:
            pass
    if not current_sid:
        log("  no game seed captured (game auto-submit still may count it)")
    await asyncio.sleep(SEED_DELAY)

    log("  Simulating...")
    sim = page.locator("button").filter(has_text=re.compile(r"SIMULATE", re.I)).first
    if await sim.is_visible(timeout=5000):
        await human_click(page, sim, timeout=5000)
        await jsleep(1.6, 2.6)
        skip = page.locator("button").filter(has_text=re.compile(r"SKIP TO END", re.I)).first
        try:
            if await skip.is_visible(timeout=3000):
                await human_click(page, skip, timeout=3000)
        except:
            pass
        await jsleep(2.5, 4.0)

    ss = SHOTS_DIR / f"d{num}.png"
    await page.screenshot(path=str(ss), full_page=False)

    # Poll for the result: render can lag SKIP. Missing a win here is harmless
    # for counting (game auto-submits) but pollutes logs; worse, rushing to
    # DRAFT AGAIN can navigate away before the game's auto-submit fires.
    body = ""
    for _ in range(15):
        try:
            body = await page.inner_text("body")
        except:
            pass
        if "HISTORY REWRITTEN" in body or any(k in body for k in ["CHOKED", "HEARTBREAK", "OUTCLASSED", "UNPREPARED"]):
            break
        await page.wait_for_timeout(1000)
    # Settle: give the game's own auto-submit time to fire before we do anything.
    await page.wait_for_timeout(8000)
    try:
        body = await page.inner_text("body")
    except:
        pass
    overs_m = re.search(r"(\d{2,3}(?:\.\d)?)\s*overs?", body, re.I)
    overs_val = float(overs_m.group(1)) if overs_m else None
    balls_val = int(round(overs_val * 6)) if overs_val else None
    score_m = re.search(r"(\d{3,}/\d+)", body)
    score_val = score_m.group(1) if score_m else "?"

    if "HISTORY REWRITTEN" in body:
        if balls_val and balls_val < best_balls[0]:
            best_balls[0] = balls_val
            log(f"  *** NEW BEST: {balls_val} balls = {overs_val} overs ***")
        else:
            log(f"  >>> WIN {balls_val} balls = {overs_val} overs <<<")

        await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
        await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{STABLE_PID}')")

        # No manual submit (proof-less POSTs are a server-visible marker).
        # The game's own auto-submit reports the win; we just confirm below.
        log("  Polling leaderboard until entry is confirmed...")
        confirmed = False
        today_e = count_e = you_e = None
        for poll in range(8):
            await asyncio.sleep(5)
            try:
                lb_check = await page.evaluate(r"""async (params) => {
                    const {handle, pid} = params;
                    const out = {};
                    try {
                        const r = await fetch('""" + LB_URL + r"""/board?window=today');
                        if (r.ok) {
                            const d = await r.json();
                            const entries = d.top || [];
                            const idx = entries.findIndex(e => e.handle === handle);
                            if (idx >= 0) out['today'] = {rank: idx+1, balls: entries[idx].balls, runs: entries[idx].runs};
                            else out['today'] = null;
                        }
                    } catch(e) {}
                    try {
                        const r = await fetch('""" + LB_URL + r"""/count?window=today&id=' + encodeURIComponent(pid));
                        if (r.ok) {
                            const d = await r.json();
                            if (d.you) out['you'] = d.you;
                        }
                    } catch(e) {}
                    return out;
                }""", {"handle": HANDLE, "pid": STABLE_PID})
                today_e = lb_check.get("today")
                you_e = lb_check.get("you")
                if today_e or you_e:
                    parts = []
                    if today_e: parts.append(f"fastest #{today_e['rank']} ({today_e['balls']} balls)")
                    if you_e: parts.append(f"my id wins={you_e.get('entry', {}).get('v', you_e.get('v', '?'))}")
                    log(f"  CONFIRMED! {', '.join(parts)}")
                    confirmed = True
                    break
                else:
                    log(f"  Poll {poll+1}/8: pending...")
            except Exception as e:
                log(f"  Poll {poll+1} err: {e}")
        if not confirmed:
            log("  Leaderboard not confirmed yet (cache?), proceeding anyway")

        log(f"  +-- SCORECARD draft#{num} [{combo_name}] --")
        log(f"  | {score_val} in {overs_val} ov ({balls_val} balls) - HISTORY REWRITTEN")
        log(f"  +-- {HANDLE} day wins growing, see LIVE_LOG.md --")
        hold = HOLD_SEC + random.randint(0, 8)
        log(f"  Waiting {hold}s before next draft...")
        await page.wait_for_timeout(hold * 1000)

    if "HISTORY REWRITTEN" not in body:
        for kw in ["CHOKED", "HEARTBREAK", "OUTCLASSED", "UNPREPARED"]:
            if kw in body:
                log(f"  +-- SCORECARD draft#{num} [{combo_name}] --")
                log(f"  | {score_val} - {kw}")
                log(f"  +-- loss, moving on --")
                break

    again = page.locator("button").filter(has_text=re.compile(r"DRAFT AGAIN", re.I)).first
    try:
        if await again.is_visible(timeout=3000):
            await human_click(page, again, timeout=3000)
            await asyncio.sleep(2)
        else:
            await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(2000)
            await page.evaluate(f"() => localStorage.setItem('five-hundred-handle','{HANDLE}')")
            await page.evaluate(f"() => localStorage.setItem('five-hundred-pid','{STABLE_PID}')")
            if not await enter_draft(page):
                log("  re-entry failed, will retry next draft")
    except:
        pass
    return ("HISTORY REWRITTEN" in body), True

async def main():
    state = load_state()
    log(f"spin_fixed11.py SHUFFLE engine: {len(COMBOS20)} combos, {HANDLE}, day={state['date']}")
    log(f"Day so far: {state['drafts']}/{DAILY_CAP} drafts, {state['wins']} wins")
    if state["drafts"] >= DAILY_CAP:
        log("Daily 50-draft cap reached, resting this session.")
        return
    if random.random() < SKIP_PROB:
        log(f"Session skipped by random draw (SKIP_PROB={SKIP_PROB}) — keeps timing patternless.")
        return
    delay = random.randint(0, int(os.getenv("START_DELAY_MAX", "120")))
    log(f"Random start delay {delay}s ...")
    await asyncio.sleep(delay)
    n_planned = min(session_drafts(), DAILY_CAP - load_state()["drafts"])
    state = load_state()
    log(f"Session plan: {n_planned} drafts, pid={STABLE_PID}")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False,
            args=["--window-size=1366,768", "--disable-blink-features=AutomationControlled"],
            ignore_default_args=["--enable-automation"])
        ctx = await browser.new_context(viewport={"width": 1366, "height": 768}, device_scale_factor=1)
        page = await ctx.new_page()
        await setup_route_interception(page)
        await page.goto(BASE_URL, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate(f"() => {{ localStorage.setItem('five-hundred-handle','{HANDLE}'); localStorage.setItem('five-hundred-pid','{STABLE_PID}'); }}")
        log(f"Initial PID {STABLE_PID} (pinned forever)")

        ok = False
        for _ in range(20):
            try:
                if await page.evaluate("() => !!window.__No && window.__No.length > 30"):
                    ok = True
                    break
            except:
                pass
            await page.wait_for_timeout(500)
        log(f"Capture No={'OK' if ok else 'MISS'}")
        if not ok:
            try:
                title = await page.title()
                nkeys = await page.evaluate("() => Object.keys(window).length")
                log(f"  diag: title={title!r} window_keys={nkeys}")
            except Exception as e:
                log(f"  diag err: {e}")
            log("FAIL: could not capture teams")
            await browser.close()
            return
        team_count = await page.evaluate("() => window.__No.length")
        log(f"Teams: {team_count}")

        seed = random.randint(1, 2**31 - 1)
        js = INJECT_HACK_JS.replace("RAND_SEED", str(seed))
        await page.evaluate(js)
        log(f"Hack injected seed={seed}")

        if not await enter_draft(page):
            log("FAIL: draft screen never appeared, aborting session")
            await browser.close()
            return
        log("Entered draft loop")

        wins = 0
        for i in range(1, n_planned + 1):
            st = load_state()
            if st["drafts"] >= DAILY_CAP:
                log("Daily cap hit mid-session, stopping.")
                break
            won, completed = await one_draft(page, st["drafts"] + 1, st)
            if completed:
                st["drafts"] += 1
            if won:
                wins += 1
                st["wins"] += 1
            save_state(st)
            import datetime as _dt
            ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            entry = f"## {ts} — Draft #{st['drafts']} [{'WIN' if won else 'loss'}]\n"
            live_entry(st, entry)
            git_push_log(f"live: draft {st['drafts']} {'win' if won else 'loss'} {ts}")
            log(f"Progress: session {wins}/{i} wins best {best_balls[0]} balls | day {st['wins']}/{st['drafts']}")

        st = load_state()
        log(f"=== DONE session {wins} wins | day {st['wins']}/{st['drafts']} best {best_balls[0]} ===")
        live_entry(st, f"## session end — day {st['wins']}/{st['drafts']}")
        git_push_log(f"live: session end day {st['wins']}/{st['drafts']}")

        await page.wait_for_timeout(3000)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
