# ArkClaw Visual & Product Design Amendment v1.1

> **Document Status**: Authoritative Amendment to Visual Design Freeze v1.0  
> **Effective Stage**: Stage 11B onwards

---

## 1. Superseded Contracts (被正式取代的契约)

### 1.1 Action Palette ROOT Structure
- **Prior Freeze**:
  - `Ask ArkClaw`
  - `Character >`
  - `System >`
- **Amendment v1.1**:
  - `Ask ArkClaw` (Opens Dashboard / Chat Mode, focuses composer)
  - `Character >` (Opens Dashboard / Character Animation page)
  - `Animation >` (Same-shell sub-layer expanding capability-driven animations for live desktop pet playback)
  - `System >` (Same-shell sub-layer for system commands & opening Settings)

### 1.2 Theme System & Preference Model
- **Prior Freeze**: Binary static switch (Light / Dark).
- **Amendment v1.1**: Two-level dynamic model:
  - `ThemePreference` $\in \{\text{SYSTEM}, \text{LIGHT}, \text{DARK}\}$
  - `EffectiveTheme` $\in \{\text{LIGHT}, \text{DARK}\}$
  - All UI surfaces consume `EffectiveTheme`. When `ThemePreference == SYSTEM`, `EffectiveTheme` dynamically tracks OS appearance.

### 1.3 Chat / Work Presentation Model
- **Prior Freeze**: Undefined single continuous chat stream.
- **Amendment v1.1**: Single primary page (`Chat / Work`) with internal segmented mode switcher:
  - **💬 Chat Mode**: Conversational companion, minimal bubble blocks (Gemini style).
  - **⚡ Work Mode**: Task & workflow view, capability-gated in Stage 11C.
  - Both modes share one authoritative `ConversationContext`, draft, and message history.

### 1.4 Cross-Surface Navigation Semantics
- **Palette $\to$ Dashboard**:
  - `Ask ArkClaw`: Activates Dashboard, selects `Chat / Work` page, activates Chat mode, focuses prompt composer.
  - `Character`: Activates Dashboard, selects `Character Animation` page.
  - `Animation`: Progressive disclosure within Palette; selecting an action dispatches `ProductionAction` directly to desktop pet.
  - `System`: Progressive disclosure within Palette; contains `Open Settings` command which opens Dashboard Settings dialog.

---

## 2. Unchanged Core Contracts (保持不变的核心契约)

1. **Qt.Tool Same-Shell Overlay**: Action Palette remains a transparent, frameless `Qt.Tool` companion surface anchored to the pet.
2. **Dashboard 3-Page Information Architecture**:
   - `Home`
   - `Chat / Work`
   - `Character Animation`
3. **Conversation State Ownership**: Single ownership in Application / Presentation coordinator; surviving palette and dashboard navigation cycles without data loss.
4. **Role & Capability Isolation**: Role packs (`schwarz-production`), manifests, and animations remain decoupled from UI presentations.
