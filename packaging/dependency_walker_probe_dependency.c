#include <windows.h>

__declspec(dllexport) int probe_dependency_value(void) {
    return 7;
}

BOOL WINAPI DllMain(
    HINSTANCE instance,
    DWORD reason,
    LPVOID reserved
) {
    (void)instance;
    (void)reason;
    (void)reserved;
    return TRUE;
}
