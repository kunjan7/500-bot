import re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app.js', encoding='utf-8').read()

for kw in ['Muralitharan', 'Tendulkar', 'KEN', 'AUS', '"1990s"', '1990s', 'era', 'ERA',
           'spinPool', 'pool', 'teams', 'TEAMS', 'legends', 'LEGENDS']:
    idxs = [m.start() for m in re.finditer(re.escape(kw), src)]
    print(kw, '->', len(idxs), idxs[:8])

# Find first Murali hit and dump context
idxs = [m.start() for m in re.finditer('Muralitharan', src)]
if idxs:
    i = idxs[0]
    print("\n=== CONTEXT around first Muralitharan ===")
    print(src[max(0,i-3000):i+1500])
