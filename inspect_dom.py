"""
500/0 DOM INSPECTOR
Navigates to 500-0.com, clicks SPIN, and prints the full page DOM
so we can find the exact selectors to use for automation.
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

URL = "https://500-0.com"
OUT = Path("dom_snapshot.txt")

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, slow_mo=500)
        ctx = await browser.new_context(viewport={"width":1280,"height":900})
        page = await ctx.new_page()

        print("[1] Navigating to 500-0.com ...")
        await page.goto(URL, wait_until="networkidle")
        await asyncio.sleep(3)

        # Dump initial DOM
        html = await page.content()
        Path("initial_dom.html").write_text(html, encoding="utf-8")
        print("[2] Saved initial_dom.html")

        # Find all buttons
        buttons = await page.evaluate("""() => {
            return [...document.querySelectorAll('button, [role="button"], [tabindex]')]
                .map(el => ({
                    tag: el.tagName,
                    text: (el.innerText||el.textContent||'').trim().slice(0,80),
                    cls:  el.className.toString().slice(0,80),
                    id:   el.id,
                    'data-*': Object.fromEntries(
                        [...el.attributes].filter(a=>a.name.startsWith('data-')).map(a=>[a.name,a.value])
                    )
                })).filter(b=>b.text);
        }""")
        print(f"[3] Found {len(buttons)} interactive elements:")
        for b in buttons:
            print(f"    [{b['tag']}] '{b['text']}'  cls='{b['cls']}'  id='{b['id']}'")

        # Screenshot
        await page.screenshot(path="step1_home.png", full_page=True)
        print("[4] Screenshot: step1_home.png")

        # Try to find and click the SPIN button
        print("[5] Looking for SPIN button ...")
        spin_found = await page.evaluate("""() => {
            const candidates = [...document.querySelectorAll('button, [role="button"], div, span')]
                .filter(el => {
                    const t = (el.innerText||el.textContent||'').trim().toUpperCase();
                    return t === 'SPIN' || t === 'SPIN THE WHEEL' || t.startsWith('SPIN');
                });
            if (candidates.length) {
                candidates[0].click();
                return {found:true, text: (candidates[0].innerText||'').trim(), cls: candidates[0].className};
            }
            return {found:false};
        }""")
        print(f"    Spin result: {spin_found}")
        await asyncio.sleep(5)

        await page.screenshot(path="step2_after_spin.png", full_page=True)
        print("[6] Screenshot: step2_after_spin.png")

        # Now inspect what's on screen
        dom_after = await page.evaluate("""() => {
            // Find all text nodes that look like player names
            const all = [...document.querySelectorAll('*')]
                .filter(el => el.children.length === 0)
                .map(el => ({
                    tag: el.tagName,
                    text: (el.innerText||el.textContent||'').trim(),
                    cls:  el.className ? el.className.toString().slice(0,60) : '',
                    parent_cls: el.parentElement ? (el.parentElement.className||'').toString().slice(0,60) : ''
                }))
                .filter(o => o.text.length > 2 && o.text.length < 50 && /^[A-Z]/.test(o.text));
            return all;
        }""")
        print(f"[7] Text elements (possible player names): {len(dom_after)}")
        for item in dom_after[:60]:
            print(f"    [{item['tag']}] '{item['text']}'  cls='{item['cls']}'")

        # Save full state HTML
        html2 = await page.content()
        Path("after_spin_dom.html").write_text(html2, encoding="utf-8")
        print("[8] Saved after_spin_dom.html")

        # All buttons after spin
        buttons2 = await page.evaluate("""() => {
            return [...document.querySelectorAll('button, [role="button"]')]
                .map(el => ({
                    text: (el.innerText||el.textContent||'').trim().slice(0,80),
                    cls:  el.className.toString().slice(0,80),
                    id:   el.id
                })).filter(b=>b.text);
        }""")
        print(f"[9] Buttons after spin: {len(buttons2)}")
        for b in buttons2[:30]:
            print(f"    '{b['text']}'  cls='{b['cls']}'")

        input("\n>>> Press ENTER to close browser ...")
        await browser.close()

asyncio.run(main())
