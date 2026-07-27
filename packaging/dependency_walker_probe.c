#include <windows.h>

__declspec(dllimport) int probe_dependency_value(void);

int main(void) {
    HANDLE marker = CreateFileW(
        L"probe_executed.marker",
        GENERIC_WRITE,
        0,
        NULL,
        CREATE_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL
    );
    if (marker == INVALID_HANDLE_VALUE) {
        return 2;
    }
    CloseHandle(marker);
    return probe_dependency_value() == 7 ? 0 : 3;
}
