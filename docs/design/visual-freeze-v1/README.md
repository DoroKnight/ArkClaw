# ArkClaw Visual Freeze v1 — Concept Renders

本目录包含 Visual Design Freeze v1 的两批统一概念稿：Desktop Companion A–D 与 `dashboard/` 下的 Full Dashboard A–E。全部使用 built-in ImageGen 生成；同批后续页面沿用母版 App Shell、tokens、字体、图标、半径与 spacing。

## Final assets

- `render-a-default-desktop.png` — Windows desktop + Reference Character visual placeholder only。
- `render-b-action-palette-root.png` — ROOT：Ask ArkClaw / Character / System。
- `render-c-character-layer.png` — same-shell Character layer、disabled reason、keyboard focus。
- `render-d-conversation-capsule.png` — content-first short conversation + rounded input。

### Full Dashboard assets

- `dashboard/render-a-dashboard-home.png` — Light Home、Ask、Recent Work、Active Character Summary、Explore。
- `dashboard/render-b-chat-work.png` — Conversation → Agent Work → Activity → Result / Artifact → Follow-up。
- `dashboard/render-c-character-animation.png` — Active Character、chibi Spine preview、capability-driven animation cards。
- `dashboard/render-d-desktop-dashboard.png` — Desktop Companion 与独立 Dashboard 的层级关系。
- `dashboard/render-e-dark-parity.png` — Navigation、Home、Composer、Result、Character Preview 的 Dark parity。

## Final prompt set

### Render A

Use case: `ui-mockup`。生成 16:9 calm Windows desktop；Reference Character 作为约 18% work-area height 的唯一 ArkClaw element，位于右下、任务栏上方；无持久 UI；近白冷灰 wallpaper；避免 HUD、neon、IDE、dashboard 与大型聊天窗口。

### Render B

Use case: `ui-mockup`。保持 Render A 不变；在 Active Character 上左侧约 12 px 处加入 304 px wide near-white Action Palette；16 px radius、1 px neutral border、subtle shadow；精确标签 `Ask ArkClaw`、`Character`、`System`；Ask row 使用 pale blue-violet hover。

### Render C

Use case: `ui-mockup` + targeted spatial edit。保持 Render A 不变；同一 304 px Palette shell；header `Character · {ActiveCharacterDisplayName}`；Pause、Resume Autonomous 与 capability-driven animation actions；Resume 显示 `Available after a manual action`；Interact 使用 pale hover + 2 px focus outline；最终把 Surface 移到 Active Character 上左侧约 12 px。

### Render D

Use case: `ui-mockup` + targeted spatial edit。保持 Render A 不变；加入 560 × 350 px Conversation Capsule；24 px radius/padding；header `What can I help with?`；plain typographic user/assistant content blocks；56 px rounded input `Ask ArkClaw...` + upward send arrow；不使用左右消息气泡；最终把 Surface 移到 Active Character 上左侧约 24 px。

### Dashboard Render A — Home

Light Theme；1280×800 independent app window；56 top shell；208 expanded nav with exactly Home、Chat / Work、Character Animation；Home greeting、720×64 Ask、最多三项 Recent Work、320×220 Active Character Summary、Explore。Character label 仅为 `Reference Character: Schwarz`；系统保持 character-agnostic。

### Dashboard Render B — Chat / Work

沿用 A 的 shell；Chat / Work active；Gemini-like content-first conversation；800×104–240 Composer；attachment chip；真实 Agent activity；720 max Result Card。证明 Chat 在同页渐进成为 Work，不出现 IDE/file tree/terminal。

### Dashboard Render C — Character Animation

沿用 A 的 shell；Character Animation active；640×480 preferred neutral chibi Spine preview；144×176 character cards；168×104 capability-driven animation cards；Preview、Play、Trigger on Desktop；unsupported 清晰可读。

### Dashboard Render D — Desktop + Dashboard

Windows desktop 同时显示小型 Active Character、compact Capsule 与独立 Dashboard window。表达 quick interaction → Capsule、complex work → Dashboard；二者不 spatially anchor，但共享 tokens 与 component language。

### Dashboard Render E — Dark Parity

保持相同 shell 与几何；dark 使用 `#17181B` background、`#1D1E22` nav、`#222327` surface、`#AEB7FF` accent；同时验证 Navigation、Home、Composer、Result / Artifact、Character Preview、Animation Cards；无 absolute black、neon、glow。

## Interpretation rule

Renders 是视觉方向参考，不是尺寸标注图。实现时以 `../07-visual-design-freeze-v1.md` 与 `../visual-freeze-v1.tokens.json` 为唯一数值来源。
