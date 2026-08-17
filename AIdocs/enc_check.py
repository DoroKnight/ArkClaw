import collections
from pathlib import Path
REPO = Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice")
bom = 0
crlf = 0
lf = 0
mixed = 0
n = 0
samples = []
for scope in [REPO/"src", REPO/"tests", REPO/"scripts", REPO/"packaging"]:
    for p in scope.rglob("*.py"):
        if "__pycache__" in p.parts: continue
        raw = p.read_bytes()
        n += 1
        has_bom = raw.startswith(b"\xef\xbb\xbf")
        crlf_c = raw.count(b"\r\n")
        lf_c = raw.count(b"\n") - crlf_c
        if has_bom: bom += 1
        if crlf_c and lf_c: mixed += 1
        elif crlf_c: crlf += 1
        else: lf += 1
        if has_bom or mixed:
            samples.append(str(p.relative_to(REPO)))
print(f"files={n} bom={bom} crlf={crlf} lf={lf} mixed={mixed}")
print("samples:", *samples[:10], sep="\n  ")
