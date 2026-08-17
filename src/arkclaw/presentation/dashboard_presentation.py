"""Qt-free Full Dashboard presentation snapshots (Slice 7C-7E).

The Dashboard pages render these snapshots and never own backend or
conversation truth (07 9 Presentation Mapping, 07 11 Desktop <-> Dashboard).
The authoritative Conversation context / draft stay in
:class:`~arkclaw.presentation.frontend_presentation.FrontendPresentationModel`
and :class:`~arkclaw.presentation.conversation_draft_safety.ConversationDraftModel`;
this module only mirrors presentation state for the Dashboard surface.  The
"Active Character" terminology comes from the frozen character model tokens,
never from a hard-coded character name; "Schwarz" may only surface as the
frozen reference character.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class AgentState(StrEnum):
    """Frozen agent work states (07 9 Agent State and Activity)."""

    IDLE = "idle"
    SUBMITTED = "submitted"
    THINKING = "thinking"
    WORKING = "working"
    WAITING = "waiting"
    NEEDS_ATTENTION = "needs_attention"
    COMPLETED = "completed"
    ERROR = "error"


class ActivityState(StrEnum):
    COMPLETED = "completed"
    CURRENT = "current"
    FUTURE = "future"
    ERROR = "error"
    WARNING = "warning"


class AttachmentState(StrEnum):
    """Frozen attachment states (07 9 Attachment)."""

    SELECTED_LOCALLY = "selected_locally"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"
    REMOVED = "removed"
    UNSUPPORTED = "unsupported"
    TOO_LARGE = "too_large"


class ResultArtifactKind(StrEnum):
    SUMMARY = "summary"
    DOCUMENT = "document"
    FILE = "file"
    GENERATED_ASSET = "generated_asset"
    CODE_ARTIFACT = "code_artifact"
    GENERIC = "generic"


class ResultArtifactState(StrEnum):
    AVAILABLE = "available"
    OPENING = "opening"
    FAILED = "failed"


class AnimationState(StrEnum):
    """Frozen Character Animation card states (07 10)."""

    IDLE = "idle"
    PREVIEWING = "previewing"
    PLAYING = "playing"
    UNSUPPORTED = "unsupported"
    TRIGGER_UNAVAILABLE = "trigger_unavailable"


@dataclass(frozen=True, slots=True)
class ActivityItem:
    text: str
    state: ActivityState = ActivityState.COMPLETED


@dataclass(frozen=True, slots=True)
class AttachmentItem:
    name: str
    kind: str
    state: AttachmentState = AttachmentState.SELECTED_LOCALLY
    detail: str | None = None

    @property
    def can_retry(self) -> bool:
        return self.state is AttachmentState.FAILED


@dataclass(frozen=True, slots=True)
class ResultArtifact:
    kind: ResultArtifactKind = ResultArtifactKind.GENERIC
    title: str = ""
    summary: str = ""
    state: ResultArtifactState = ResultArtifactState.AVAILABLE
    actions: tuple[str, ...] = ("preview", "open", "export_or_save")


@dataclass(frozen=True, slots=True)
class RecentWorkItem:
    title: str
    subtitle: str = ""


@dataclass(frozen=True, slots=True)
class ActiveCharacterSummary:
    """Active Character presentation (07 4, 07 10).

    ``display_name`` is the character model name when available; the section
    title always uses the frozen product term "Active Character".  When the
    active character is the frozen reference character, ``is_reference`` is
    True so the UI can render "Reference Character: Schwarz" exactly.
    """

    available: bool = True
    display_name: str = ""
    is_reference: bool = False
    reference_name: str | None = None
    unavailable_reason: str | None = None


@dataclass(frozen=True, slots=True)
class HomeSnapshot:
    """Frozen Home sections (07 8): greeting, Ask, Recent Work, Character."""

    first_launch: bool = False
    greeting: str = ""
    intro: str = ""
    agent_state: AgentState = AgentState.IDLE
    agent_task_title: str | None = None
    recent_work: tuple[RecentWorkItem, ...] = ()
    active_character: ActiveCharacterSummary = ActiveCharacterSummary()


@dataclass(frozen=True, slots=True)
class ChatWorkSnapshot:
    """Frozen Chat / Work sections (07 9)."""

    conversation_id: str | None = None
    agent_state: AgentState = AgentState.IDLE
    agent_task_title: str | None = None
    activity: tuple[ActivityItem, ...] = ()
    attachments: tuple[AttachmentItem, ...] = ()
    result: ResultArtifact | None = None
    composer_placeholder: str = "Ask ArkClaw\u2026"


@dataclass(frozen=True, slots=True)
class AnimationItem:
    """One capability-driven animation inventory row (07 10)."""

    action_id: str
    name: str
    state: AnimationState = AnimationState.IDLE
    disabled_reason: str | None = None


@dataclass(frozen=True, slots=True)
class CharacterAnimationSnapshot:
    """Frozen Character Animation page (07 10)."""

    active_character: ActiveCharacterSummary = ActiveCharacterSummary()
    available_characters: tuple[str, ...] = ()
    animations: tuple[AnimationItem, ...] = ()
    preview_loading: bool = False
    preview_error: str | None = None


class DashboardPresentationModel:
    """Single-owner presentation snapshots for the Full Dashboard pages.

    The model holds no application truth: it mirrors what real adapters feed
    it.  When a source is absent the snapshot stays in its explicit empty /
    unavailable state so the UI never fabricates recent work or character
    data (07 8, 07 10).
    """

    def __init__(
        self,
        home: HomeSnapshot | None = None,
        chat_work: ChatWorkSnapshot | None = None,
        character: CharacterAnimationSnapshot | None = None,
    ) -> None:
        self._home = home if home is not None else HomeSnapshot()
        self._chat_work = chat_work if chat_work is not None else ChatWorkSnapshot()
        self._character = (
            character if character is not None else CharacterAnimationSnapshot()
        )

    @property
    def home(self) -> HomeSnapshot:
        return self._home

    @property
    def chat_work(self) -> ChatWorkSnapshot:
        return self._chat_work

    @property
    def character(self) -> CharacterAnimationSnapshot:
        return self._character

    def set_home(self, snapshot: HomeSnapshot) -> None:
        self._home = snapshot

    def set_chat_work(self, snapshot: ChatWorkSnapshot) -> None:
        self._chat_work = snapshot

    def set_character(self, snapshot: CharacterAnimationSnapshot) -> None:
        self._character = snapshot


def character_summary_from_pack_id(
    pack_id: str | None,
    *,
    available: bool = True,
    is_reference: bool = False,
    reference_name: str | None = None,
    unavailable_reason: str | None = None,
) -> ActiveCharacterSummary:
    """Build the Active Character summary from a role-pack id.

    The display name is derived deterministically from the pack id (e.g.
    ``schwarz-production`` -> ``Schwarz``); it is a presentation mapping, not
    fabricated backend state.  ``is_reference`` marks the frozen reference
    character so UI copy can use "Reference Character: Schwarz".
    """
    if pack_id is None:
        return ActiveCharacterSummary(
            available=available,
            unavailable_reason=unavailable_reason,
        )
    return ActiveCharacterSummary(
        available=available,
        display_name=_display_name(pack_id),
        is_reference=is_reference,
        reference_name=reference_name,
        unavailable_reason=unavailable_reason,
    )


def animation_items_from_capabilities(
    capabilities: Mapping[str, str],
) -> tuple[AnimationItem, ...]:
    """Build the capability-driven animation inventory.

    ``capabilities`` maps action ids to the manifest display names exactly as
    the Active Character manifest provides.  Only provided capabilities
    appear, so unsupported actions are never fabricated (07 10).  Order is
    stable and derived from the mapping.
    """
    return tuple(
        AnimationItem(action_id=action_id, name=name)
        for action_id, name in capabilities.items()
    )


def _display_name(pack_id: str) -> str:
    parts = [part for part in pack_id.replace("-", " ").replace("_", " ").split() if part]
    if parts and parts[-1].lower() == "production":
        parts = parts[:-1]
    if not parts:
        return "Active Character"
    return " ".join(part[:1].upper() + part[1:] for part in parts)


__all__ = [
    "ActiveCharacterSummary",
    "ActivityItem",
    "ActivityState",
    "AgentState",
    "AnimationItem",
    "AnimationState",
    "AttachmentItem",
    "AttachmentState",
    "CharacterAnimationSnapshot",
    "ChatWorkSnapshot",
    "DashboardPresentationModel",
    "HomeSnapshot",
    "RecentWorkItem",
    "ResultArtifact",
    "ResultArtifactKind",
    "ResultArtifactState",
    "animation_items_from_capabilities",
    "character_summary_from_pack_id",
]
