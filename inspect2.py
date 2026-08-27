import re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

html = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\draft_dom.html', encoding='utf-8').read()
print('LEN:', len(html))
btns = re.findall(r'<button[^>]*>.*?</button>', html, re.S)
print('BUTTON COUNT:', len(btns))
for i, b in enumerate(btns):
    txt = re.sub(r'<[^>]+>', '|', b)
    txt = re.sub(r'\|+', '|', txt).strip()
    print(i, '::', txt[:200].replace('\n', ' '))

# Also dump overall visible text structure
body = re.search(r'<body[^>]*>(.*)</body>', html, re.S)
text = re.sub(r'<script.*?</script>', '', html, flags=re.S)
text = re.sub(r'<style.*?</style>', '', text, flags=re.S)
# Show tag structure of main containers
divs = re.findall(r'<(div|section|main|aside)[^>]*class="([^"]*)"', html)
seen = []
for tag, cls in divs:
    if cls not in seen:
        seen.append(cls)
print('\nUNIQUE CLASSES (%d):' % len(seen))
for c in seen[:80]:
    print('  ', c)
