import ctypes, ctypes.wintypes, os, time
os.environ.setdefault("QT_QPA_PLATFORM", "windows")
from PySide6.QtCore import QObject, QEvent, Qt, QAbstractNativeEventFilter, QByteArray
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtGui import QContextMenuEvent

app = QApplication.instance() or QApplication([])
log = []
class F(QObject):
    def eventFilter(self, obj, event):
        if isinstance(event, QContextMenuEvent):
            log.append(("CTXMENU", obj.objectName(), str(event.reason())))
        elif event.type() == QEvent.Type.MouseButtonPress:
            log.append(("PRESS", obj.objectName(), str(event.button())))
        elif event.type() == QEvent.Type.MouseButtonRelease:
            log.append(("RELEASE", obj.objectName(), str(event.button())))
        return super().eventFilter(obj, event)
class Native(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, message):
        try:
            t = bytes(event_type.data()) if isinstance(event_type, QByteArray) else bytes(event_type)
            if t in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
                msg = ctypes.cast(int(message), ctypes.POINTER(ctypes.wintypes.MSG)).contents
                names = {0x0201:"LBDN", 0x0202:"LBUP", 0x0204:"RBDN", 0x0205:"RBUP", 0x007B:"CTXMENU", 0x0200:"MOVE", 0x0084:"HIT"}
                if msg.message in names:
                    log.append(("NAT", names[msg.message], int(msg.hWnd)))
        except Exception:
            pass
        return False

w = QWidget()
w.setObjectName("plain")
w.resize(200, 200); w.move(300, 300); w.show()
f = F(); w.installEventFilter(f)
nt = Native(); app.installNativeEventFilter(nt)
app.processEvents()
user32 = ctypes.windll.user32
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]; user32.SetCursorPos.restype = ctypes.wintypes.BOOL
user32.GetWindowRect.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.RECT)]; user32.GetWindowRect.restype = ctypes.wintypes.BOOL
user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]; user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
rect = ctypes.wintypes.RECT(); user32.GetWindowRect(int(w.winId()), ctypes.byref(rect))
pt = ctypes.wintypes.POINT((rect.left+rect.right)//2, (rect.top+rect.bottom)//2)
user32.SetForegroundWindow(int(w.winId())); app.processEvents(); time.sleep(0.2)
user32.SetCursorPos(pt.x, pt.y)
log.clear()
user32.mouse_event(0x0008, 0, 0, 0, None); time.sleep(0.05); user32.mouse_event(0x0010, 0, 0, 0, None)
deadline = time.monotonic() + 4.0
while time.monotonic() < deadline:
    app.processEvents()
    if any(e[0] in ("CTXMENU",) or (e[0]=="NAT" and e[1]=="CTXMENU") for e in log):
        break
    time.sleep(0.01)
print("after right click:")
for e in log: print(e)
