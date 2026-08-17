import subprocess, pathlib
out = pathlib.Path(r"D:\ArkClaw\docs\ARKCLAW_UI_DESIGN_V1.md")
data = subprocess.check_output(["git", "show", "stash@{0}:ARKCLAW_UI_DESIGN_V1.md"], cwd=r"D:\ArkClaw")
out.write_bytes(data)
print("extracted bytes:", len(data))
print("head:", data[:80])