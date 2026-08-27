import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

lines = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app_pretty.js', encoding='utf-8').read().splitlines()
kws = ['simulat', 'chase', 'innings', 'boundary', 'wicket', 'six', 'four', 'over',
       'pow', 'bat', 'bwl', 'rating', 'target', '500']
for i, ln in enumerate(lines, 1):
    low = ln.lower()
    if any(k in low for k in kws):
        s = ln.strip()
        print(f"{i:5d}: {s[:170]}")
