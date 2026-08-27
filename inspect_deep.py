"""
500/0 DEEP DOM INSPECTOR
Clicks DRAFT (starts game), then SPIN, then shows full DOM structure
for player cards so we can build accurate automation selectors.
"""
import asyncio
import pathlib
import re
from playwright.async_api import async_playwright

URL = "https://500-0.com"

async def dump_all_elements(page, label):
    result = await page.evaluate("""() => {
        const out = [];
        document.querySelectorAll('*').forEach(el => {
            const t = (el.innerText || el.textContent || '').trim();
            if (t.length > 1 && t.length < 80 && el.children.length < 3) {
                out.push({
                    tag: el.tagName,
                    text: t.slice(0, 70),
                    cls:  (el.className || '').toString().slice(0, 100),
                    id:   el.id || '',
                    clickable: el.tagName === 'BUTTON' || el.onclick != null || el.getAttribute('role') === 'button'
                });
            }
        });
        return out;
    }""")
    print(f"\n{'='*60}")
    print(f"  DOM STATE: {label}  ({len(result)} elements)")
    print(f"{'='*60}")
    for item in result:
        marker = "[BTN]" if item['clickable'] else "     "
        print(f"{marker} [{item['tag']}] '{item['text']}'")
        if item['cls']:
            print(f"       cls: {item['cls']}")

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=600)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await ctx.new_page()

        # Step 1: Load game
        print("[1] Loading 500-0.com ...")
        await page.goto(URL, wait_until="networkidle")
        await asyncio.sleep(2)
        await page.screenshot(path="screenshots/s1_home.png")

        # Step 2: Click EASY mode
        print("[2] Clicking EASY mode ...")
        await page.click("text=EASY")
        await asyncio.sleep(1)
        await page.screenshot(path="screenshots/s2_easy.png")

        # Step 3: Click DRAFT button
        print("[3] Clicking DRAFT ...")
        await page.click("text=DRAFT")
        await asyncio.sleep(3)
        await page.screenshot(path="screenshots/s3_draft_started.png")

        html = await page.content()
        pathlib.Path("draft_dom.html").write_text(html, encoding="utf-8")
        await dump_all_elements(page, "AFTER CLICKING DRAFT")

        # Step 4: Look for SPIN button now
        print("\n[4] Looking for SPIN button in draft mode ...")
        buttons = await page.query_selector_all("button")
        for btn in buttons:
            t = await btn.inner_text()
            cls = await btn.get_attribute("class") or ""
            print(f"  BTN: '{t.strip()[:60]}'  cls='{cls[:80]}'")

        # Step 5: Click SPIN
        print("\n[5] Clicking SPIN ...")
        spin_clicked = False
        for btn in buttons:
            t = (await btn.inner_text()).strip().upper()
            if "SPIN" in t:
                await btn.click()
                spin_clicked = True
                print(f"  Clicked: '{t}'")
                break
        if not spin_clicked:
            # Try by text
            try:
                await page.click("button:has-text('SPIN')")
                spin_clicked = True
            except Exception:
                pass

        await asyncio.sleep(4)
        await page.screenshot(path="screenshots/s4_after_spin.png")

        html2 = await page.content()
        pathlib.Path("after_spin_dom.html").write_text(html2, encoding="utf-8")
        await dump_all_elements(page, "AFTER SPIN")

        # Step 6: All buttons now
        print("\n[6] All buttons after spin:")
        buttons2 = await page.query_selector_all("button")
        for btn in buttons2:
            t = await btn.inner_text()
            cls = await btn.get_attribute("class") or ""
            print(f"  BTN: '{t.strip()[:80]}'")
            print(f"       cls='{cls[:100]}'")

        # Extract player-name-looking text
        print("\n[7] Extracting possible player names (capital-letter words 8-35 chars):")
        all_text = await page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('*').forEach(el => {
                const t = (el.innerText || '').trim();
                if (t.length >= 5 && t.length <= 40 && /^[A-Z][a-z]+ [A-Z]/.test(t)) {
                    out.push({
                        text: t,
                        tag: el.tagName,
                        cls: (el.className||'').toString().slice(0,80),
                        parent_cls: (el.parentElement ? (el.parentElement.className||'') : '').toString().slice(0,80)
                    });
                }
            });
            return out;
        }""")
        for item in all_text[:40]:
            print(f"  [{item['tag']}] '{item['text']}'  cls='{item['cls']}'  parent='{item['parent_cls']}'")

        input("\n>>> Press ENTER to close ...")
        await browser.close()

# Create screenshots dir
pathlib.Path("screenshots").mkdir(exist_ok=True)
asyncio.run(main())
