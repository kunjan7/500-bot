"""Debug: compare textContent vs innerText for card buttons."""
import asyncio, sys, re
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False, args=["--window-size=480,1000"])
        ctx = await browser.new_context(viewport={"width": 480, "height": 1000}, device_scale_factor=2)
        page = await ctx.new_page()

        async def intercept(route):
            resp = await route.fetch()
            body = await resp.text()
            body = body.replace("analysis:Z}}var Mc=", "analysis:Z}}window.__f6=f6;window.__a6=a6;window.__n6=n6;var Mc=")
            body = body.replace("];function c6(){", "];window.__vo=vo;window.__K2=K2;function c6(){")
            await route.fulfill(response=resp, body=body, content_type="application/javascript")
        await page.route("**/*app*.js", intercept)

        await page.goto("https://500-0.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)
        await page.locator("button").filter(has_text=re.compile("^EASY")).first.click()
        await asyncio.sleep(0.5)
        await page.locator("button").filter(has_text=re.compile("^DRAFT$")).first.click()
        await asyncio.sleep(2)
        await page.locator("button").filter(has_text=re.compile("^SPIN$")).first.click()
        await asyncio.sleep(3)

        result = await page.evaluate(r"""() => {
            const out = [];
            document.querySelectorAll("button").forEach((btn, i) => {
                const tc = (btn.textContent || "").trim();
                if (tc.length < 10) return;
                const lines = tc.split(/\n/).map(l => l.trim()).filter(Boolean);
                const roles = ["BATTER","BOWLER","WK","ALL-ROUNDER"];
                out.push({i, tc_len: tc.length, lines: lines.length,
                    first: lines[0], second: lines[1] || "",
                    hasRole: roles.includes((lines[1]||"").toUpperCase()),
                    opacity: getComputedStyle(btn).opacity,
                    disabled: btn.disabled
                });
            });
            return out;
        }""")
        for r in result[:8]:
            print(f'  [{r["i"]}] tc_len={r["tc_len"]} lines={r["lines"]} '
                  f'first={r["first"]!r} second={r["second"]!r} '
                  f'hasRole={r["hasRole"]} opacity={r["opacity"]} disabled={r["disabled"]}')
        await browser.close()

asyncio.run(main())
