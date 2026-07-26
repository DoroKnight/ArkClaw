"""Fixed credential Targets used only by explicit manual verification tools.

Importing this module performs no credential, client, environment, or network
access. The resolver accepts only the two reviewed manual-test identifiers.
"""

from __future__ import annotations

from typing import ClassVar

from sjtuclaw.domain.models import (
    DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID,
    OPENAI_MANUAL_TEST_CREDENTIAL_ID,
    CredentialId,
)
from sjtuclaw.infrastructure.security.windows_credential_store import (
    CredentialTargetResolutionError,
)

OPENAI_MANUAL_TEST_TARGET = "SJTUClaw/Test/OpenAI/APIKey"
DEEPSEEK_MANUAL_TEST_TARGET = "SJTUClaw/Test/DeepSeek/APIKey"


class ManualCredentialTargetResolver:
    """Resolve exactly the two fixed manual-verification credential Targets."""

    _TARGETS: ClassVar[dict[CredentialId, str]] = {
        OPENAI_MANUAL_TEST_CREDENTIAL_ID: OPENAI_MANUAL_TEST_TARGET,
        DEEPSEEK_MANUAL_TEST_CREDENTIAL_ID: DEEPSEEK_MANUAL_TEST_TARGET,
    }

    @classmethod
    def resolve(cls, credential_id: CredentialId) -> str:
        if not isinstance(credential_id, CredentialId):
            raise TypeError("credential_id must be a CredentialId")
        target = cls._TARGETS.get(credential_id)
        if target is None:
            raise CredentialTargetResolutionError() from None
        return target
