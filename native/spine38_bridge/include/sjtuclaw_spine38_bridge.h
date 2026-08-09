#ifndef SJTUCLAW_SPINE38_BRIDGE_H
#define SJTUCLAW_SPINE38_BRIDGE_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#if defined(SJTUCLAW_SPINE38_BRIDGE_BUILD)
#define SJTUCLAW_SPINE38_API __declspec(dllexport)
#else
#define SJTUCLAW_SPINE38_API __declspec(dllimport)
#endif
#else
#define SJTUCLAW_SPINE38_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum SjtuclawSpine38Code {
    SJTUCLAW_SPINE38_OK = 0,
    SJTUCLAW_SPINE38_INVALID_ARGUMENT = 1,
    SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED = 2,
    SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED = 3,
    SJTUCLAW_SPINE38_ANIMATION_NOT_FOUND = 4,
    SJTUCLAW_SPINE38_RUNTIME_FAILURE = 5
} SjtuclawSpine38Code;

typedef struct SjtuclawSpine38Handle SjtuclawSpine38Handle;

typedef struct SjtuclawSpine38Bounds {
    float x;
    float y;
    float width;
    float height;
} SjtuclawSpine38Bounds;

#define SJTUCLAW_SPINE38_PLAYBACK_ABI 1

typedef enum SjtuclawSpine38BlendMode {
    SJTUCLAW_SPINE38_BLEND_NORMAL = 0,
    SJTUCLAW_SPINE38_BLEND_ADDITIVE = 1,
    SJTUCLAW_SPINE38_BLEND_MULTIPLY = 2,
    SJTUCLAW_SPINE38_BLEND_SCREEN = 3
} SjtuclawSpine38BlendMode;

typedef struct SjtuclawSpine38Vertex {
    float x;
    float y;
    float u;
    float v;
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
} SjtuclawSpine38Vertex;

typedef struct SjtuclawSpine38DrawView {
    const SjtuclawSpine38Vertex* vertices;
    size_t vertex_count;
    const uint32_t* indices;
    size_t index_count;
    uint32_t texture_page;
    uint32_t blend_mode;
    int32_t draw_order;
} SjtuclawSpine38DrawView;

/*
 * ABI version 1 ownership and buffer rules:
 *
 * - create copies/parses both input spans before returning; the caller retains
 *   ownership of those spans and may release them after create returns.
 * - destroy accepts NULL. A non-NULL handle must be destroyed exactly once.
 * - *_name_size returns the required destination capacity in bytes, including
 *   the trailing NUL. Zero means the handle/index was invalid or an internal
 *   failure occurred.
 * - *_info copies the exact UTF-8 name, including its trailing NUL. The call
 *   returns INVALID_ARGUMENT when the buffer is NULL or too small. No output
 *   is modified when an *_info or setup_bounds call fails.
 * - Catalog names are copied into caller-owned buffers; this API returns no
 *   borrowed catalog-name pointers. Any borrowed view pointer added within
 *   ABI version 1 remains valid only until the next mutating call on the same
 *   handle or until destroy, whichever occurs first.
 * - draw_view requires view_capacity >= sizeof(SjtuclawSpine38DrawView) and
 *   copies the view descriptor into caller memory. Its vertex/index pointers
 *   borrow immutable, handle-owned storage. They remain valid until the next
 *   successful set_animation call, the next update call with valid arguments,
 *   or destroy. Callers that need longer lifetimes must copy both spans.
 * - Failed calls do not modify caller-owned output structs.
 * - Functions returning size_t return zero for NULL handles and on internal
 *   failures. No C++ exception is allowed to cross this C ABI.
 */

SJTUCLAW_SPINE38_API uint32_t sjtuclaw_spine38_abi_version(void);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_create(
    const uint8_t* skeleton,
    size_t skeleton_size,
    const char* atlas,
    size_t atlas_size,
    SjtuclawSpine38Handle** out_handle);

SJTUCLAW_SPINE38_API void sjtuclaw_spine38_destroy(
    SjtuclawSpine38Handle* handle);

SJTUCLAW_SPINE38_API size_t sjtuclaw_spine38_animation_count(
    const SjtuclawSpine38Handle* handle);

SJTUCLAW_SPINE38_API size_t sjtuclaw_spine38_animation_name_size(
    const SjtuclawSpine38Handle* handle,
    size_t index);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_animation_info(
    const SjtuclawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity,
    float* duration_seconds);

SJTUCLAW_SPINE38_API size_t sjtuclaw_spine38_skin_count(
    const SjtuclawSpine38Handle* handle);

SJTUCLAW_SPINE38_API size_t sjtuclaw_spine38_skin_name_size(
    const SjtuclawSpine38Handle* handle,
    size_t index);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_skin_info(
    const SjtuclawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_setup_bounds(
    const SjtuclawSpine38Handle* handle,
    SjtuclawSpine38Bounds* out_bounds);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_set_animation(
    SjtuclawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_update(
    SjtuclawSpine38Handle* handle,
    float delta_seconds);

SJTUCLAW_SPINE38_API size_t sjtuclaw_spine38_draw_count(
    const SjtuclawSpine38Handle* handle);

SJTUCLAW_SPINE38_API SjtuclawSpine38Code sjtuclaw_spine38_draw_view(
    const SjtuclawSpine38Handle* handle,
    size_t index,
    SjtuclawSpine38DrawView* out_view,
    size_t view_capacity);

#ifdef __cplusplus
}
#endif

#endif
