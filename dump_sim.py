import re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app.js', encoding='utf-8').read()

def show(kw, before=200, after=1500, max_hits=3):
    idxs = [m.start() for m in re.finditer(re.escape(kw), src)]
    print("#", kw, "->", len(idxs), "hits")
    for i in idxs[:max_hits]:
        print("-" * 60)
        print(src[max(0,i-before):i+after])
    print()

show('RE-ROLL', 600, 300, 2)
show('"SPIN"', 800, 200, 2)
show('no legal slot', 900, 200, 1)
