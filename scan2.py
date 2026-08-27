import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app.js', encoding='utf-8').read()

def show(center, before=600, after=1400, label=""):
    print("=" * 30, label or str(center), "=" * 30)
    print(src[max(0, center-before):center+after])
    print()

show(367872, 800, 800, "SIMULATE BUTTON")
show(25909, 400, 1200, "random#1")
show(149335, 400, 1500, "random#2")
