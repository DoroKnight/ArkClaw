"""Qt-free Full Dashboard presentation snapshot contracts (Slice 7C-7E).

Authority: docs/design/07-visual-design-freeze-v1.md sections 8/9/10 and the
frozen character_model tokens ("Active Character" product term, "Schwarz"
reference character, "Visual placeholder" label).
"""

from __future__ import annotations

from arkclaw.presentation.dashboard_presentation import (
    AgentState,
    AnimationItem,
    AnimationState,
    AttachmentItem,
    AttachmentState,
    CharacterAnimationSnapshot,
    ChatWorkSnapshot,
    DashboardPresentationModel,
    HomeSnapshot,
    RecentWorkItem,
    ResultArtifact,
    ResultArtifactKind,
    ResultArtifactState,
    animation_items_from_capabilities,
    character_summary_from_pack_id,
)
from arkclaw.presentation.qt.theme.design_tokens import load_design_tokens


def test_frozen_agent_states_are_exact() -> None:
    assert [state.value for state in AgentState] == [
        "idle",
        "submitted",
        "thinking",
        "working",
        "waiting",
        "needs_attention",
        "completed",
        "error",
    ]


def test_frozen_attachment_states_are_exact() -> None:
    assert [state.value for state in AttachmentState] == [
        "selected_locally",
        "uploading",
        "uploaded",
        "failed",
        "removed",
        "unsupported",
        "too_large",
    ]


def test_frozen_character_terminology_comes_from_tokens() -> None:
    tokens = load_design_tokens()
    assert tokens.product_term == "Active Character"
    assert tokens.reference_character == "Schwarz"
    assert tokens.component["dashboard"]["character_animation"][
        "inventory_source"
    ] == "active_character_capability_manifest"


def test_home_snapshot_defaults_show_no_fake_data() -> None:
    home = HomeSnapshot()
    assert home.recent_work == ()
    assert home.agent_state is AgentState.IDLE
    assert home.active_character.available is True


def test_home_snapshot_first_launch_and_recent_work() -> None:
    home = HomeSnapshot(
        first_launch=True,
        greeting="Welcome",
        recent_work=(
            RecentWorkItem("Implement palette", "Chat / Work"),
            RecentWorkItem("Animate idle", "Character Animation"),
        ),
    )
    assert home.first_launch is True
    assert len(home.recent_work) == 2


def test_attachment_retry_only_when_failed() -> None:
    failed = AttachmentItem("spec.png", "image", AttachmentState.FAILED)
    uploaded = AttachmentItem("spec.png", "image", AttachmentState.UPLOADED)
    assert failed.can_retry is True
    assert uploaded.can_retry is False


def test_result_artifact_defaults() -> None:
    artifact = ResultArtifact()
    assert artifact.kind is ResultArtifactKind.GENERIC
    assert artifact.state is ResultArtifactState.AVAILABLE
    assert artifact.actions == ("preview", "open", "export_or_save")


def test_animation_items_are_capability_driven() -> None:
    capabilities = {
        "relax": "Relax",
        "sit": "Sit",
        "interact": "Interact",
    }
    items = animation_items_from_capabilities(capabilities)
    assert [item.action_id for item in items] == ["relax", "sit", "interact"]
    assert [item.name for item in items] == ["Relax", "Sit", "Interact"]
    assert all(item.state is AnimationState.IDLE for item in items)


def test_animation_items_never_fabricate_unsupported() -> None:
    partial = animation_items_from_capabilities({"relax": "Relax"})
    assert len(partial) == 1
    assert partial[0].action_id == "relax"


def test_schwarz_production_manifest_inventory() -> None:
    schwarz_manifest = {
        "relax": "Relax",
        "move": "Move",
        "sit": "Sit",
        "sleep": "Sleep",
        "special": "Special",
        "interact": "Interact",
    }
    items = animation_items_from_capabilities(schwarz_manifest)
    assert [item.action_id for item in items] == [
        "relax",
        "move",
        "sit",
        "sleep",
        "special",
        "interact",
    ]


def test_character_summary_from_pack_id() -> None:
    summary = character_summary_from_pack_id(
        "schwarz-production",
        is_reference=True,
        reference_name="Schwarz",
    )
    assert summary.available is True
    assert summary.display_name == "Schwarz"
    assert summary.is_reference is True
    assert summary.reference_name == "Schwarz"


def test_character_summary_unavailable() -> None:
    summary = character_summary_from_pack_id(
        "schwarz-production",
        available=False,
        unavailable_reason="Spine assets are missing",
    )
    assert summary.available is False
    assert summary.unavailable_reason == "Spine assets are missing"


def test_character_summary_without_pack_id() -> None:
    summary = character_summary_from_pack_id(None)
    assert summary.available is True
    assert summary.display_name == ""


def test_dashboard_model_holds_snapshots() -> None:
    model = DashboardPresentationModel()
    assert model.home == HomeSnapshot()
    assert model.chat_work == ChatWorkSnapshot()
    assert model.character == CharacterAnimationSnapshot()
    home = HomeSnapshot(greeting="Hello")
    model.set_home(home)
    model.set_chat_work(ChatWorkSnapshot(conversation_id="c1"))
    model.set_character(
        CharacterAnimationSnapshot(animations=(AnimationItem("relax", "Relax"),))
    )
    assert model.home is home
    assert model.chat_work.conversation_id == "c1"
    assert model.character.animations[0].name == "Relax"


def test_character_snapshot_defaults() -> None:
    snapshot = CharacterAnimationSnapshot()
    assert snapshot.available_characters == ()
    assert snapshot.animations == ()
    assert snapshot.preview_error is None
    assert snapshot.active_character.available is True
