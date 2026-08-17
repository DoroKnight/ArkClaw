"""Qt test-suite hygiene (Slice 7 P0 lifecycle / cross-test isolation).

Widgets scheduled with ``deleteLater()`` are not destroyed until the event
loop processes their ``DeferredDelete`` events.  In one shared-process pytest
run the C++ objects would otherwise survive into the next test and pollute
``QApplication.topLevelWidgets()``-based ownership assertions (Slice 6B review
gate: the Action Palette and 6B suites must run in one process; Slice 7
requires the same isolation for the Dashboard top-level).  Flushing only the
pending DeferredDelete events is the narrow, standard Qt teardown idiom: it
never closes windows owned by other fixtures and never alters behavior.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication, QEvent


@pytest.fixture(autouse=True)
def flush_qt_deferred_deletes() -> None:
    """Process pending DeferredDelete events after every Qt test."""
    yield
    application = QCoreApplication.instance()
    if application is not None:
        QCoreApplication.sendPostedEvents(
            None,
            QEvent.Type.DeferredDelete,
        )
