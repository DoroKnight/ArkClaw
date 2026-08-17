import ctypes, ctypes.wintypes, os, time, traceback
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from typing import Any, cast
from PySide6.QtCore import QObject, QEvent, QByteArray, Qt, Signal, QAbstractNativeEventFilter
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QContextMenuEvent
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
class TraceFilter(QObject):
    def __init__(self, tag, log):
        super().__init__(); self.tag = tag; self.log = log
    def eventFilter(self, obj, event):
        if isinstance(event, QContextMenuEvent):
            self.log.append((self.tag, "QContextMenuEvent", str(event.reason()), (event.globalPos().x(), event.globalPos().y())))
        elif event.type() == QEvent.Type.MouseButtonPress:
            self.log.append((self.tag, "MousePress", str(event.button())))
        elif event.type() == QEvent.Type.MouseButtonRelease:
            self.log.append((self.tag, "MouseRelease", str(event.button())))
        return super().eventFilter(obj, event)
class NativeTrace(QAbstractNativeEventFilter):
    def __init__(self, log):
        super().__init__(); self.log = log; self.done = False
    def nativeEventFilter(self, event_type, message):
        try:
            t = bytes(event_type.data()) if isinstance(event_type, QByteArray) else bytes(event_type)
            if t in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                if not self.done:
                    self.done = True
                    print("MSG dir:", [f for f in dir(ctypes.wintypes.MSG)])
                msg = ctypes.cast(int(message), ctypes.POINTER(ctypes.wintypes.MSG)).contents
                names = {0x0084:"WM_NCHITTEST", 0x0204:"WM_RBUTTONDOWN", 0x0205:"WM_RBUTTONUP", 0x007B:"WM_CONTEXTMENU", 0x0201:"WM_LBUTTONDOWN", 0x0202:"WM_LBUTTONUP", 0x0200:"WM_MOUSEMOVE"}
                if msg.message in names:
                    self.log.append(("NATIVE", names[msg.message], int(msg.hWnd), int(msg.pt.x), int(msg.pt.y)))
        except Exception:
            self.log.append(("NATIVE_EXC", traceback.format_exc(limit=3)))
        return False

app = QApplication.instance() or QApplication([])
print("platform:", app.platformName())
log = []
native_trace = NativeTrace(log)
app.installNativeEventFilter(native_trace)
composition = create_optional_production_pet_composition()
assert composition is not None
window = SpyWindow(renderer=composition.renderer, track0=composition.track0,
    active_role_pack_id=composition.role_pack_id,
    available_production_actions=composition.available_actions,
    playback_event_source=composition.playback_event_source)
overlay = window._effect_overlay
assert overlay is not None
trace_overlay = TraceFilter("OVERLAY", log)
trace_window = TraceFilter("PETWINDOW", log)
overlay.installEventFilter(trace_overlay)
window.installEventFilter(trace_window)
bridge = StubBridge()
main_window = StubMainWindow()
coordinator = PetApplicationCoordinator(cast(QtRuntimeBridge, bridge), cast(MainWindow, main_window), window)
window.show()
app.processEvents()
user32 = ctypes.windll.user32
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
user32.SetCursorPos.restype = ctypes.wintypes.BOOL
user32.WindowFromPoint.argtypes = [ctypes.wintypes.POINT]
user32.WindowFromPoint.restype = ctypes.wintypes.HWND
user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]
user32.GetWindowRect.restype = ctypes.wintypes.BOOL
outcome = window.request_user_pet_action(ProductionAction.SIT)
deadline = time.monotonic() + 8.0
while outcome is not ActionOutcome.ACCEPTED and time.monotonic() < deadline:
    window.physics_timer.timeout.emit(); app.processEvents(); time.sleep(0.01)
    outcome = window.request_user_pet_action(ProductionAction.SIT)
print("SIT outcome:", outcome)
window.physics_timer.timeout.emit(); app.processEvents(); overlay.repaint(); app.processEvents()
layout = window._active_render_layout
print("layout mode:", layout.mode, "overlay visible:", overlay.isVisible())
rect = ctypes.wintypes.RECT()
user32.GetWindowRect(int(overlay.winId()), ctypes.byref(rect))
print("overlay rect:", rect.left, rect.top, rect.right, rect.bottom, "logical size:", overlay.width(), overlay.height())
from PySide6.QtCore import QPoint
bc = QPoint(round(layout.body_window_offset.x) + window.width()//2, round(layout.body_window_offset.y) + window.height()//2)
nw = rect.right - rect.left; nh = rect.bottom - rect.top
pt = ctypes.wintypes.POINT(rect.left + round(bc.x()*nw/overlay.width()), rect.top + round(bc.y()*nh/overlay.height()))
print("click point:", pt.x, pt.y, "WindowFromPoint == overlay:", int(user32.WindowFromPoint(pt)) == int(overlay.winId()))
log.clear()
print("--- RIGHT CLICK ---")
assert user32.SetCursorPos(pt.x, pt.y)
user32.mouse_event(0x0008, 0, 0, 0, None); time.sleep(0.03); user32.mouse_event(0x0010, 0, 0, 0, None)
deadline = time.monotonic() + 4.0
while time.monotonic() < deadline:
    app.processEvents()
    if window.palette_signals:
        break
    time.sleep(0.01)
for entry in log:
    if entry[0] == "NATIVE_EXC":
        print(entry[1])
    else:
        print(entry)
print("palette signals:", len(window.palette_signals))
print("host is None:", coordinator.palette_sink.host is None)
coordinator._remove_outside_dismiss_routing()
app.processEvents()


