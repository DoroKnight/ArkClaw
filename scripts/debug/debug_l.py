import ctypes, ctypes.wintypes, os, time
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from typing import Any, cast
from PySide6.QtCore import QObject, Qt, Signal, QEvent, QPoint
from PySide6.QtWidgets import QApplication
from arkclaw.bootstrap.pet_production import create_optional_production_pet_composition
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.main_window import MainWindow
from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome

class StubBridge(QObject):
    shutdown_finished = Signal(bool, str)
class StubMainWindow:
    def __init__(self): self.safe_close_count = 0
    def request_safe_close(self): self.safe_close_count += 1
    def update_pet_presentation(self, *a): pass
class SpyWindow(PetWindow):
    def __init__(self, **kw):
        self.palette_signals = []
        super().__init__(**kw)
        self.action_palette_requested.connect(self._on_palette)
    def _on_palette(self): self.palette_signals.append(time.monotonic())

app = QApplication.instance() or QApplication([])
log = []
composition = create_optional_production_pet_composition()
assert composition is not None
window = SpyWindow(renderer=composition.renderer, track0=composition.track0,
    active_role_pack_id=composition.role_pack_id,
    available_production_actions=composition.available_actions,
    playback_event_source=composition.playback_event_source)
overlay = window._effect_overlay
assert overlay is not None
bridge = StubBridge(); main_window = StubMainWindow()
coordinator = PetApplicationCoordinator(cast(QtRuntimeBridge, bridge), cast(MainWindow, main_window), window)
window.show(); app.processEvents()
user32 = ctypes.windll.user32
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]; user32.SetCursorPos.restype = ctypes.wintypes.BOOL
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]; user32.WindowFromPoint.restype = ctypes.wintypes.HWND
user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]; user32.GetWindowRect.restype = ctypes.wintypes.BOOL
user32.GetForegroundWindow.restype = ctypes.wintypes.HWND

def pump(pred, timeout=4.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if pred(): return True
        time.sleep(0.005)
    app.processEvents(); return bool(pred())

outcome = window.request_user_pet_action(ProductionAction.SIT)
deadline = time.monotonic() + 8.0
while outcome is not ActionOutcome.ACCEPTED and time.monotonic() < deadline:
    window.physics_timer.timeout.emit(); app.processEvents(); time.sleep(0.01)
    outcome = window.request_user_pet_action(ProductionAction.SIT)
window.physics_timer.timeout.emit(); app.processEvents(); overlay.repaint(); app.processEvents()
layout = window._active_render_layout
rect = ctypes.wintypes.RECT(); user32.GetWindowRect(int(overlay.winId()), ctypes.byref(rect))
bc = QPoint(round(layout.body_window_offset.x) + window.width()//2, round(layout.body_window_offset.y) + window.height()//2)
nw = rect.right - rect.left; nh = rect.bottom - rect.top
pt = ctypes.wintypes.POINT(rect.left + round(bc.x()*nw/overlay.width()), rect.top + round(bc.y()*nh/overlay.height()))
user32.SetCursorPos(pt.x, pt.y)
user32.mouse_event(0x0008, 0, 0, 0, None); time.sleep(0.03); user32.mouse_event(0x0010, 0, 0, 0, None)
assert pump(lambda: coordinator.palette_sink.host is not None)
host = coordinator.palette_sink.host
host.activateWindow(); app.processEvents(); time.sleep(0.2); app.processEvents()
print("host active:", host.isActiveWindow(), "fg:", int(user32.GetForegroundWindow()))
def on_focus_changed(w):
    log.append(("focusWindowChanged", str(w)))
def on_state(s):
    log.append(("applicationStateChanged", str(s)))
app.focusWindowChanged.connect(on_focus_changed)
app.applicationStateChanged.connect(on_state)
class HF(QObject):
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.WindowDeactivate, QEvent.Type.WindowActivate, QEvent.Type.ActivationChange):
            log.append(("HOSTEV", str(event.type()), obj is host))
        return False
hf = HF()
host.installEventFilter(hf)
screen = QApplication.primaryScreen(); geometry = screen.availableGeometry()
excluded = (int(overlay.winId()), int(host.winId()), int(window.winId()))
cands = ((geometry.left()+6, geometry.top()+6), (geometry.right()-8, geometry.top()+6), (geometry.left()+6, geometry.bottom()-8), (geometry.right()-8, geometry.bottom()-8))
outside = None
for x, y in cands:
    p = ctypes.wintypes.POINT(x, y)
    if int(user32.WindowFromPoint(p)) not in excluded:
        outside = p; break
print("outside:", outside.x, outside.y, "WFP:", int(user32.WindowFromPoint(outside)))
user32.SetCursorPos(outside.x, outside.y)
log.append(("---click---",))
user32.mouse_event(0x0002, 0, 0, 0, None); time.sleep(0.03); user32.mouse_event(0x0004, 0, 0, 0, None)
time.sleep(0.8); app.processEvents()
for e in log: print(e)
print("host visible after outside click:", host.isVisible())
print("fg after:", int(user32.GetForegroundWindow()))
print("app state:", app.applicationState())
coordinator._remove_outside_dismiss_routing()
