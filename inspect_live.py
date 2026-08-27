"""
Live flow inspector for 500-0.com
Walks: home -> EASY -> DRAFT -> SPIN -> pick -> ... -> SIMULATE -> result
Dumps DOM + screenshots + network log at every step.
"""
import sys, time, json, pathlib
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from playwright.sync_api import sync_playwright

BASE = pathlib.Path(r"C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live")
BASE.mkdir(exist_ok=True)
URL = "https://500-0.com"

netlog = []

def on_response(resp):
    try:
        req = resp.request
        if req.resource_type in ("xhr", "fetch") or ".json" in resp.url:
            entry = {"url": resp.url, "status": resp.status, "method": req.method,
                     "post": (req.post_data or "")[:2000]}
            try:
                entry["body"] = resp.text()[:8000]
            except Exception:
                pass
            netlog.append(entry)
    except Exception:
        pass

def dump(page, name):
    try:
        (BASE / (name + ".html")).write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(BASE / (name + ".png")), full_page=True)
        txt = page.evaluate("() => document.body.innerText")
        (BASE / (name + ".txt")).write_text(txt, encoding="utf-8")
        print("--- " + name + " TEXT ---")
        print(txt[:1500])
        print("--- END ---")
    except Exception as e:
        print("  dump err:", e)

def click_text(page, text, exact=False):
    for b in page.query_selector_all("button, [role=button], a"):
        try:
            t = (b.inner_text() or "").strip()
        except Exception:
            continue
        if not t:
            continue
        ok = (t.upper() == text.upper()) if exact else (text.upper() in t.upper())
        if ok:
            print("  clicking:", repr(t[:60]))
            b.click()
            return True
    print("  NOT FOUND:", repr(text))
    return False

def pick_first_player(page, tag):
    for b in page.query_selector_all("button"):
        try:
            t = (b.inner_text() or "").strip()
        except Exception:
            continue
        if any(k in t for k in ("BATTER", "BOWLER", "ALL-ROUNDER", "WK")) and "\n" in t:
            cls = b.get_attribute("class") or ""
            if "opacity" in cls and ("30" in cls or "40" in cls or "50" in cls):
                continue
            print("  [" + tag + "] picking:", repr(t.splitlines()[0][:40]), "| cls:", cls[:100])
            b.click()
            return True
    print("  [" + tag + "] NO PICK POSSIBLE")
    return False

def handle_position_popup(page):
    time.sleep(1.2)
    bt = page.evaluate("() => document.body.innerText")
    low = bt.lower()
    if "position" not in low and "bat at" not in low and "choose" not in low:
        return False
    for b in page.query_selector_all("button"):
        try:
            t = (b.inner_text() or "").strip()
            if t.isdigit() and 1 <= int(t) <= 11:
                print("  position popup: choosing", t)
                b.click()
                time.sleep(1.0)
                return True
        except Exception:
            pass
    return False

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    ctx = browser.new_context(viewport={"width": 480, "height": 960})
    page = ctx.new_page()
    page.on("response", on_response)
    console_msgs = []
    page.on("console", lambda m: console_msgs.append("[" + m.type + "] " + m.text))

    page.goto(URL, wait_until="networkidle", timeout=60000)
    time.sleep(3)
    dump(page, "01_home")

    click_text(page, "EASY"); time.sleep(1)
    click_text(page, "DRAFT"); time.sleep(3)
    dump(page, "02_draft_screen")

    if not click_text(page, "SPIN"):
        click_text(page, "START") or click_text(page, "GO")
    time.sleep(4.5)
    dump(page, "03_spin1")

    pick_first_player(page, "slot01")
    handle_position_popup(page)
    dump(page, "04_after_pick1")

    for slot in range(2, 12):
        st = "slot%02d" % slot
        if not click_text(page, "SPIN"):
            print("  SPIN button missing at", st)
        time.sleep(4.5)
        pick_first_player(page, st)
        handle_position_popup(page)

    dump(page, "07_full_squad")

    sim = click_text(page, "SIMULATE") or click_text(page, "CHASE") or click_text(page, "PLAY MATCH") or click_text(page, "START MATCH")
    print("simulate clicked:", sim)
    time.sleep(35)
    dump(page, "08_result_35s")
    time.sleep(25)
    dump(page, "09_result_60s")

    (BASE / "network_log.json").write_text(json.dumps(netlog, indent=2), encoding="utf-8")
    (BASE / "console_log.txt").write_text("\n".join(console_msgs)[-30000:], encoding="utf-8")
    print("NET ENTRIES:", len(netlog))
    for e in netlog[:25]:
        print(" ", e["method"], e["status"], e["url"][:110])
    browser.close()
