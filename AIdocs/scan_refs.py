import re, sys
from pathlib import Path

ROOTS = [Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\src"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\tests"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\scripts"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\packaging")]

pat = re.compile(r"(from|import)\s+(arkclaw\.(?:application|presentation\.qt)(?:\.\w+)*)")
string_pat = re.compile(r"['\"]arkclaw\.(?:application|presentation\.qt)[\.\w]*['\"]")

imports = {}
strings = {}
for root in ROOTS:
    for p in sorted(root.rglob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        for i, line in enumerate(text.splitlines(), 1):
            m = pat.search(line)
            if m:
                imports.setdefault(p.relative_to(root.parent.parent), []).append((i, line.strip()))
            s = string_pat.search(line)
            if s and not m:
                strings.setdefault(p.relative_to(root.parent.parent), []).append((i, line.strip()))

print("=== IMPORT STATEMENTS ===")
for f, hits in imports.items():
    print(f"## {f}")
    for i, line in hits:
        print(f"  {i}: {line}")
print()
print("=== STRING LITERALS (not import stmts) ===")
for f, hits in strings.items():
    print(f"## {f}")
    for i, line in hits:
        print(f"  {i}: {line}")
