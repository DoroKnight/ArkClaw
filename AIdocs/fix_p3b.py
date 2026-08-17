from pathlib import Path
wt = Path(r"D:\ArkClaw\.worktrees\arkpets-spine-idle-vertical-slice")
struct = (wt / "STRUCTURE.md").read_text(encoding="utf-8")
hand = (wt / "docs" / "HANDOFF_CURRENT_ARCHITECTURE.md").read_text(encoding="utf-8")

B = {"v": "\u2502", "t": "\u251c", "b": "\u2514", "h": "\u2500"}

s_lines = struct.splitlines()
idx = next(i for i, l in enumerate(s_lines) if l.startswith(B["t"] + B["h"] + " infrastructure/"))
end = next(i for i in range(idx + 1, len(s_lines)) if s_lines[i].startswith(B["t"] + B["h"] + " presentation/qt/"))
block = s_lines[idx:end]

new_lines = []
for l in block:
    if l.startswith(B["t"] + B["h"] + " ") or l.startswith(B["b"] + B["h"] + " "):
        new_lines.append(B["v"] + "  " + l)
    elif l.startswith(B["v"] + "  "):
        new_lines.append(B["v"] + "  " + l)
    else:
        raise AssertionError("unexpected line: " + l)

h_lines = hand.splitlines()
hidx = next(i for i, l in enumerate(h_lines) if l == B["v"] + "  " + B["t"] + B["h"] + " infrastructure/")
hend = next(i for i in range(hidx + 1, len(h_lines)) if h_lines[i].startswith(B["v"] + "  " + B["t"] + B["h"] + " presentation/qt/"))

old_region = h_lines[hidx:hend]
print("OLD REGION:")
for l in old_region:
    print(repr(l))
print("NEW REGION:")
for l in new_lines:
    print(repr(l))

replaced = h_lines[:hidx] + new_lines + h_lines[hend:]
nl = "\r\n" if "\r\n" in hand else "\n"
hand2 = nl.join(replaced) + ("\r\n" if "\r\n" in hand else "\n")
(wt / "docs" / "HANDOFF_CURRENT_ARCHITECTURE.md").write_text(hand2, encoding="utf-8")
print("HANDOFF infrastructure tree fixed")