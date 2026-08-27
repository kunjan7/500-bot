import re, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

src = open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app.js', encoding='utf-8').read()
print("orig len:", len(src), "lines:", src.count("\n"))

# Simple JS beautifier: newline after ; { } and before }
out = []
depth = 0
in_str = None
i = 0
while i < len(src):
    c = src[i]
    if in_str:
        out.append(c)
        if c == "\\" and i + 1 < len(src):
            out.append(src[i+1]); i += 2; continue
        if c == in_str:
            in_str = None
        i += 1
        continue
    if c in ('"', "'", '`'):
        in_str = c; out.append(c); i += 1; continue
    if c == '{':
        depth += 1; out.append(c); out.append('\n' + '  ' * depth); i += 1; continue
    if c == '}':
        depth -= 1; out.append('\n' + '  ' * depth + c + ('\n' + '  ' * depth if depth > 0 else '')); i += 1; continue
    if c == ';':
        out.append(c); out.append('\n' + '  ' * depth); i += 1; continue
    out.append(c); i += 1

pretty = ''.join(out)
open(r'C:\Users\KUNJAN\.gemini\antigravity\scratch\500-bot\live\app_pretty.js', 'w', encoding='utf-8').write(pretty)
print("pretty lines:", pretty.count("\n"))
