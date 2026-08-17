from pathlib import Path
p = Path(r"D:\ArkClaw\docs\engineering\repository-architecture-review.md")
raw = p.read_text(encoding="utf-8")
old = "*报告结束。下一阶段建议：批准本报告 → 执行 Phase 0（基线刻画）→ 再按阶段推进。*"
new = "*报告结束。审计与结构整理（P0–P5）均已完成并通过回归验证，执行记录见 §17；`origin/main` 推送与后续清理项见 §17.4。*"
assert raw.count(old) == 1, "closing line not found"
p.write_text(raw.replace(old, new), encoding="utf-8")
print("closing line updated")