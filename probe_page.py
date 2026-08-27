"""Probe: navigate to draft page, show buttons."""
import asyncio, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx = await browser.new_context(viewport={"width": 480, "height": 1000}, device_scale_factor=2)
        page = await ctx.new_page()

        async def intercept(route):
            resp = await route.fetch()
            body = await resp.text()
            body = body.replace(
                "analysis:Z}}var Mc=",
                "analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc="
            )
            body = body.replace(
                "];function c6(){",
                "];window.__vo=vo;window.__K2=K2;function c6(){"
            )
            await route.fulfill(response=resp, body=body, content_type="application/javascript")
        await page.route("**/*app*.js", intercept)

        await page.goto("https://500-0.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.evaluate("() => localStorage.setItem('five-hundred-handle', 'kunjan1387')")

        # Click EASY
        easy = page.locator("button").filter(has_text="EASY").first
        await easy.click()
        await page.wait_for_timeout(1000)
        print("Clicked EASY")

        # Click DRAFT
        draft = page.locator("button").filter(has_text="DRAFT").first
        await draft.click()
        await page.wait_for_timeout(2000)
        print("Clicked DRAFT")

        # Show page state
        text = await page.inner_text("body")
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        print("=== PAGE TEXT (first 40 lines) ===")
        for l in lines[:40]:
            print(f"  {l}")

        print("\n=== BUTTONS ===")
        btns = page.locator("button")
        c = await btns.count()
        for i in range(min(c, 30)):
            t = (await btns.nth(i).inner_text()).strip()
            vis = await btns.nth(i).is_visible()
            if t and vis:
                print(f"  [{i}] '{t[:60]}' visible={vis}")

        # Check for SPIN
        print("\n=== SPIN search ===")
        spin = page.locator("button").filter(has_text="SPIN")
        spin_c = await spin.count()
        print(f"  SPIN buttons found: {spin_c}")
        if spin_c:
            for i in range(spin_c):
                t = (await spin.nth(i).inner_text()).strip()
                vis = await spin.nth(i).is_visible()
                print(f"  SPIN[{i}]: '{t}' visible={vis}")

        # Capture verification
        has_vo = await page.evaluate("() => !!window.__vo")
        vo_count = await page.evaluate("() => window.__vo ? window.__vo.length : 0")
        print(f"\n=== Capture: vo={has_vo} ({vo_count} teams), f6={await page.evaluate('() => !!window.__f6')} ===")

        # If SPIN found, click it and show cards
        if spin_c:
            print("\n=== Clicking SPIN ===")
            await spin.first.click()
            await page.wait_for_timeout(3000)

            text2 = await page.inner_text("body")
            lines2 = [l.strip() for l in text2.split("\n") if l.strip()]
            print("=== AFTER SPIN (first 40 lines) ===")
            for l in lines2[:40]:
                print(f"  {l}")

            print("\n=== BUTTONS AFTER SPIN ===")
            c2 = await btns.count()
            for i in range(min(c2, 30)):
                t = (await btns.nth(i).inner_text()).strip()
                vis = await btns.nth(i).is_visible()
                if t and vis:
                    print(f"  [{i}] '{t[:60]}' visible={vis}")

        await page.screenshot(path="shots_hack/probe_draft.png")
        await browser.close()

asyncio.run(main())
