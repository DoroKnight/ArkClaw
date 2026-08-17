import re
from pathlib import Path

ROOTS = [Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\src"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\tests"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\scripts"),
         Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice\packaging")]

# direct-submodule import forms: from arkclaw.application import <names>  and  from arkclaw.presentation.qt import <names>
for root in ROOTS:
    for p in sorted(root.rglob("*.py")):
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i]
            m = re.match(r"\s*from\s+(arkclaw\.application|arkclaw\.presentation\.qt)\s+import\s+(.*)$", line)
            if m:
                # gather continuation
                stmt = m.group(2)
                j = i
                while (stmt.rstrip().endswith("(") or (stmt.count("(") > stmt.count(")"))) and j+1 < len(lines):
                    j += 1
                    stmt += " " + lines[j].strip()
                names = re.findall(r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:,|$|\()", stmt)
                print(f"{p.relative_to(root.parent.parent)}:{i+1}  [{m.group(1)}]  names={names}")
                print(f"    stmt: {stmt.strip()[:160]}")
                i = j
            i += 1
