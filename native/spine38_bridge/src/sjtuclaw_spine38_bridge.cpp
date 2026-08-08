#if defined(_WIN32)
#define SJTUCLAW_SPINE38_EXPORT __declspec(dllexport)
#else
#define SJTUCLAW_SPINE38_EXPORT
#endif

extern "C" SJTUCLAW_SPINE38_EXPORT int sjtuclaw_spine38_abi_version() {
    return 1;
}
