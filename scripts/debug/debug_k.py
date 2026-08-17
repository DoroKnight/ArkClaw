import ctypes, ctypes.wintypes, os, time, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from typing import Any, cast
from PySide6.QtCore import QObject, QEvent, QByteArray, Qt, Signal, QAbstractNativeEventFilter, QPoint
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QContextMenuEvent
from arkclaw.bootstrap.pet_production import create_optional_production_pet_composition
from arkclaw.presentation.qt.pet.pet_window import PetWindow
from arkclaw.presentation.qt.pet_application import PetApplicationCoordinator
from arkclaw.presentation.qt.platform.runtime_bridge import QtRuntimeBridge
from arkclaw.presentation.qt.ui.main_window import MainWindow
from arkclaw.application.pet.pet_production_actions import ProductionAction
from arkclaw.application.pet.pet_track0 import ActionOutcome
from arkclaw.application.pet.pet_render_layout import PetRenderSurfaceMode

class StubBridge(QObject):
    shutdown_finished = Signal(bool, str)
class StubMainWindow:
    def __init__(self): self.safe_close_count = 0
    def request_safe_close(self): self.safe_close_count += 1
    def update_pet_presentation(self, *a): pass
class SpyWindow(PetWindow):
    def __init__(self, **kw):
        self.palette_signals = []
        self.actions = []
        super().__init__(**kw)
        self.action_palette_requested.connect(self._on_palette)
    def _on_palette(self): self.palette_signals.append(time.monotonic())
    def request_pet_action(self, action):
        self.actions.append(action)
        return super().request_pet_action(action)
class TraceFilter(QObject):
    def __init__(self, tag, log):
        super().__init__(); self.tag = tag; self.log = log
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.MouseButtonPress:
            self.log.append((self.tag, "Press", str(event.button()), event.globalPosition().x(), event.globalPosition().y(), str(obj)))
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self.log.append((self.tag, "Release", str(event.button()), event.globalPosition().x(), event.globalPosition().y(), str(obj)))
        elif isinstance(event, QContextMenuEvent):
            self.log.append((self.tag, "CtxMenu", str(event.reason())))
        return super().eventFilter(obj, event)

app = QApplication.instance() or QApplication([])
print("platform:", app.platformName())
log = []
composition = create_optional_production_pet_composition()
assert composition is not None
window = SpyWindow(renderer=composition.renderer, track0=composition.track0,
    active_role_pack_id=composition.role_pack_id,
    available_production_actions=composition.available_actions,
    playback_event_source=composition.playback_event_source)
overlay = window._effect_overlay
assert overlay is not None
tf = TraceFilter("OVERLAY", log)
tw = TraceFilter("PETWINDOW", log)
overlay.installEventFilter(tf)
window.installEventFilter(tw)
bridge = StubBridge(); main_window = StubMainWindow()
coordinator = PetApplicationCoordinator(cast(QtRuntimeBridge, bridge), cast(MainWindow, main_window), window)
window.show(); app.processEvents()
user32 = ctypes.windll.user32
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]; user32.SetCursorPos.restype = ctypes.wintypes.BOOL
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]; user32.WindowFromPoint.restype = ctypes.wintypes.HWND
user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]; user32.GetWindowRect.restype = ctypes.wintypes.BOOL
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]; user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]; user32.GetClassNameW.restype = ctypes.c_int

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
print("SIT:", outcome)
window.physics_timer.timeout.emit(); app.processEvents(); overlay.repaint(); app.processEvents()
layout = window._active_render_layout
rect = ctypes.wintypes.RECT(); user32.GetWindowRect(int(overlay.winId()), ctypes.byref(rect))
bc = QPoint(round(layout.body_window_offset.x) + window.width()//2, round(layout.body_window_offset.y) + window.height()//2)
nw = rect.right - rect.left; nh = rect.bottom - rect.top
pt = ctypes.wintypes.POINT(rect.left + round(bc.x()*nw/overlay.width()), rect.top + round(bc.y()*nh/overlay.height()))
print("schwarz pt:", pt.x, pt.y, "WFP==overlay:", int(user32.WindowFromPoint(pt)) == int(overlay.winId()))
# open palette
log.clear()
user32.SetCursorPos(pt.x, pt.y)
user32.mouse_event(0x0008, 0, 0, 0, None); time.sleep(0.03); user32.mouse_event(0x0010, 0, 0, 0, None)
assert pump(lambda: coordinator.palette_sink.host is not None)
host = coordinator.palette_sink.host
assert host is not None and host.isVisible()
print("host:", host, "winId:", int(host.winId()), "geom:", host.geometry())
# position away
screen = QApplication.primaryScreen(); geometry = screen.availableGeometry()
corners = ((geometry.left(), geometry.top()), (geometry.right()-260, geometry.top()), (geometry.left(), geometry.bottom()-320), (geometry.right()-260, geometry.bottom()-320))
corner = max(corners, key=lambda c: (c[0]-pt.x)**2 + (c[1]-pt.y)**2)
host.move(corner[0], corner[1]); app.processEvents()
hr = ctypes.wintypes.RECT(); user32.GetWindowRect(int(host.winId()), ctypes.byref(hr))
print("host moved rect:", hr.left, hr.top, hr.right, hr.bottom)
print("WFP at schwarz pt == overlay:", int(user32.WindowFromPoint(pt)) == int(overlay.winId()))
fg = int(user32.GetForegroundWindow())
print("foreground:", fg, "overlay:", int(overlay.winId()), "host:", int(host.winId()), "window:", int(window.winId()))
log.clear()
print("--- LEFT CLICK on Schwarz while palette open ---")
user32.SetCursorPos(pt.x, pt.y)
user32.mouse_event(0x0002, 0, 0, 0, None); time.sleep(0.03); user32.mouse_event(0x0004, 0, 0, 0, None)
time.sleep(0.5); app.processEvents()
for e in log: print(e)
print("actions:", window.actions)
epoch = composition.track0.state.confirmed_epoch
print("epoch:", epoch.physical_name if epoch else None)
print("host visible:", host.isVisible())
coordinator._remove_outside_dismiss_routing()
