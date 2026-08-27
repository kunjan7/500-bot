import re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

html = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\03_spin1.html', encoding='utf-8').read()

# Find buttons by their opening tags and extract balanced blocks
idx = html.find('transition-opacity')
print("first transition-opacity idx:", idx)
start = html.rfind('<button', 0, idx)
# balanced extraction
depth = 0; i = start
while i < len(html):
    if html[i] == '<':
        m = re.match(r'<(/?)(button|div|span|svg|p|h\d)\b', html[i:])
        if m:
            tag = m.group(2)
            if m.group(1) == '/':
                depth -= 1
            else:
                nxt = html.find('>', i)
                closing = html[nxt-1] == '/'
                selfclose_tag = tag in ('svg',)
                if not closing:
                    depth += 1
    i += 1
    if depth <= 0 and i > start + 10:
        break
block = html[start:i]
print("PLAYER CARD BLOCK (len %d):" % len(block))
print(block[:3000])
