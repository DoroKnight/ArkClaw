#ifndef ARKCLAW_SPINE38_BRIDGE_H
#define ARKCLAW_SPINE38_BRIDGE_H

#include <stddef.h>
#include <stdint.h>

#if defined(_WIN32)
#if defined(ARKCLAW_SPINE38_BRIDGE_BUILD)
#define ARKCLAW_SPINE38_API __declspec(dllexport)
#else
#define ARKCLAW_SPINE38_API __declspec(dllimport)
#endif
#else
#define ARKCLAW_SPINE38_API
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef enum ArkClawSpine38Code {
    ARKCLAW_SPINE38_OK = 0,
    ARKCLAW_SPINE38_INVALID_ARGUMENT = 1,
    ARKCLAW_SPINE38_ATLAS_LOAD_FAILED = 2,
    ARKCLAW_SPINE38_SKELETON_LOAD_FAILED = 3,
    ARKCLAW_SPINE38_ANIMATION_NOT_FOUND = 4,
    ARKCLAW_SPINE38_RUNTIME_FAILURE = 5
} ArkClawSpine38Code;

typedef struct ArkClawSpine38Handle ArkClawSpine38Handle;

typedef struct ArkClawSpine38Bounds {
    float x;
    float y;
    float width;
    float height;
} ArkClawSpine38Bounds;

typedef struct ArkClawSpine38RootTransform {
    float x;
    float y;
} ArkClawSpine38RootTransform;

#define ARKCLAW_SPINE38_PLAYBACK_ABI 1
#define ARKCLAW_SPINE38_EVENT_ABI 1
#define ARKCLAW_SPINE38_TEXTURE_ABI 1

typedef enum ArkClawSpine38BlendMode {
    ARKCLAW_SPINE38_BLEND_NORMAL = 0,
    ARKCLAW_SPINE38_BLEND_ADDITIVE = 1,
    ARKCLAW_SPINE38_BLEND_MULTIPLY = 2,
    ARKCLAW_SPINE38_BLEND_SCREEN = 3
} ArkClawSpine38BlendMode;

typedef enum ArkClawSpine38TextureFilter {
    ARKCLAW_SPINE38_FILTER_UNKNOWN = 0,
    ARKCLAW_SPINE38_FILTER_NEAREST = 1,
    ARKCLAW_SPINE38_FILTER_LINEAR = 2
} ArkClawSpine38TextureFilter;

typedef struct ArkClawSpine38TexturePageView {
    uint32_t min_filter;
    uint32_t mag_filter;
} ArkClawSpine38TexturePageView;

typedef struct ArkClawSpine38Vertex {
    float x;
    float y;
    float u;
    float v;
    uint8_t r;
    uint8_t g;
    uint8_t b;
    uint8_t a;
} ArkClawSpine38Vertex;

typedef struct ArkClawSpine38DrawView {
    const ArkClawSpine38Vertex* vertices;
    size_t vertex_count;
    const uint32_t* indices;
    size_t index_count;
    uint32_t texture_page;
    uint32_t blend_mode;
    int32_t draw_order;
} ArkClawSpine38DrawView;

typedef enum ArkClawSpine38EventType {
    ARKCLAW_SPINE38_EVENT_COMPLETE = 1,
    ARKCLAW_SPINE38_EVENT_LOOP_BOUNDARY = 2
} ArkClawSpine38EventType;

typedef struct ArkClawSpine38EventView {
    uint32_t event_type;
    uint32_t track;
    uint64_t loop_ordinal;
    const char* animation_name_utf8;
    size_t animation_name_size;
} ArkClawSpine38EventView;

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
 * - draw_view requires view_capacity >= sizeof(ArkClawSpine38DrawView) and
 *   copies the view descriptor into caller memory. Its vertex/index pointers
 *   borrow immutable, handle-owned storage. They remain valid until the next
 *   successful set_animation call, the next update call with valid arguments,
 *   or destroy. Callers that need longer lifetimes must copy both spans.
 * - Failed calls do not modify caller-owned output structs.
 * - event_view borrows its UTF-8 animation name from the handle. The view is
 *   valid until the next successful set_animation/clear_track call, the next
 *   valid update call, or destroy. Copy it before another mutating call.
 * - Functions returning size_t return zero for NULL handles and on internal
 *   failures. No C++ exception is allowed to cross this C ABI.
 */

ARKCLAW_SPINE38_API uint32_t arkclaw_spine38_abi_version(void);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_create(
    const uint8_t* skeleton,
    size_t skeleton_size,
    const char* atlas,
    size_t atlas_size,
    ArkClawSpine38Handle** out_handle);

ARKCLAW_SPINE38_API void arkclaw_spine38_destroy(
    ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_animation_count(
    const ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_animation_name_size(
    const ArkClawSpine38Handle* handle,
    size_t index);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_animation_info(
    const ArkClawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity,
    float* duration_seconds);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_skin_count(
    const ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_skin_name_size(
    const ArkClawSpine38Handle* handle,
    size_t index);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_skin_info(
    const ArkClawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_setup_bounds(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38Bounds* out_bounds);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_root_transform(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38RootTransform* out_transform);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_set_animation(
    ArkClawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_mix_animation(
    ArkClawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop,
    float mix_seconds);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_update(
    ArkClawSpine38Handle* handle,
    float delta_seconds);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_clear_track(
    ArkClawSpine38Handle* handle,
    uint32_t track);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_event_count(
    const ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_event_view(
    const ArkClawSpine38Handle* handle,
    size_t index,
    ArkClawSpine38EventView* out_view,
    size_t view_capacity);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_texture_page_view(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38TexturePageView* out_view,
    size_t view_capacity);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_draw_count(
    const ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_draw_view(
    const ArkClawSpine38Handle* handle,
    size_t index,
    ArkClawSpine38DrawView* out_view,
    size_t view_capacity);

#ifdef __cplusplus
}
#endif

#endif
