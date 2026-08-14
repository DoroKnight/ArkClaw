#include "arkclaw_spine38_bridge.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

#ifndef ARKCLAW_SPINE38_PLAYBACK_ABI
typedef enum ArkClawSpine38BlendMode {
    ARKCLAW_SPINE38_BLEND_NORMAL = 0,
    ARKCLAW_SPINE38_BLEND_ADDITIVE = 1,
    ARKCLAW_SPINE38_BLEND_MULTIPLY = 2,
    ARKCLAW_SPINE38_BLEND_SCREEN = 3
} ArkClawSpine38BlendMode;

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

extern "C" {
ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_set_animation(
    ArkClawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_update(
    ArkClawSpine38Handle* handle,
    float delta_seconds);

ARKCLAW_SPINE38_API size_t arkclaw_spine38_draw_count(
    const ArkClawSpine38Handle* handle);

ARKCLAW_SPINE38_API ArkClawSpine38Code arkclaw_spine38_draw_view(
    const ArkClawSpine38Handle* handle,
    size_t index,
    ArkClawSpine38DrawView* out_view,
    size_t view_capacity);
}
#endif

#ifndef ARKCLAW_SPINE38_EVENT_ABI
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

extern "C" {
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
}
#endif

namespace {

int failures = 0;

constexpr char animation_name_fixture[] = "idle-\xE7\x8C\xAB";

void check(bool condition, const char* expression, int line) {
    if (!condition) {
        std::cerr << "line " << line << ": check failed: " << expression
                  << '\n';
        ++failures;
    }
}

#define CHECK(expression) check((expression), #expression, __LINE__)

void append_varint(std::vector<uint8_t>& bytes, uint32_t value) {
    do {
        uint8_t next = static_cast<uint8_t>(value & 0x7fu);
        value >>= 7u;
        if (value != 0u) {
            next = static_cast<uint8_t>(next | 0x80u);
        }
        bytes.push_back(next);
    } while (value != 0u);
}

void append_string(std::vector<uint8_t>& bytes, const std::string& value) {
    append_varint(bytes, static_cast<uint32_t>(value.size() + 1u));
    bytes.insert(bytes.end(), value.begin(), value.end());
}

void append_float(std::vector<uint8_t>& bytes, float value) {
    uint32_t bits = 0;
    static_assert(sizeof(bits) == sizeof(value));
    std::memcpy(&bits, &value, sizeof(bits));
    bytes.push_back(static_cast<uint8_t>((bits >> 24u) & 0xffu));
    bytes.push_back(static_cast<uint8_t>((bits >> 16u) & 0xffu));
    bytes.push_back(static_cast<uint8_t>((bits >> 8u) & 0xffu));
    bytes.push_back(static_cast<uint8_t>(bits & 0xffu));
}

void append_color(
    std::vector<uint8_t>& bytes,
    uint8_t r,
    uint8_t g,
    uint8_t b,
    uint8_t a) {
    bytes.push_back(r);
    bytes.push_back(g);
    bytes.push_back(b);
    bytes.push_back(a);
}

void append_empty_animation(
    std::vector<uint8_t>& bytes,
    const std::string& name) {
    append_string(bytes, name);
    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 0);  // bone timelines
    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
}

std::vector<uint8_t> make_synthetic_skeleton(
    bool include_zero_duration_animation = false) {
    std::vector<uint8_t> bytes;

    append_string(bytes, "contract-fixture");
    append_string(bytes, "3.8.99");
    append_float(bytes, -2.0f);
    append_float(bytes, 3.0f);
    append_float(bytes, 4.0f);
    append_float(bytes, 5.0f);
    bytes.push_back(0);  // nonessential

    append_varint(bytes, 1);  // string table
    append_string(bytes, "fixture-skin");

    append_varint(bytes, 1);  // bones
    append_string(bytes, "root");
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(0);         // skin required

    append_varint(bytes, 0);  // slots
    append_varint(bytes, 0);  // IK constraints
    append_varint(bytes, 0);  // transform constraints
    append_varint(bytes, 0);  // path constraints
    append_varint(bytes, 0);  // default skin slots

    append_varint(bytes, 1);  // additional skins
    append_varint(bytes, 1);  // skin name string-table reference
    append_varint(bytes, 0);  // skin bones
    append_varint(bytes, 0);  // skin IK constraints
    append_varint(bytes, 0);  // skin transform constraints
    append_varint(bytes, 0);  // skin path constraints
    append_varint(bytes, 0);  // skin slots

    append_varint(bytes, 0);  // events
    append_varint(bytes, include_zero_duration_animation ? 2 : 1);
    if (include_zero_duration_animation) {
        append_empty_animation(bytes, "Default");
    }
    append_string(bytes, animation_name_fixture);

    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 1);  // bone timeline groups
    append_varint(bytes, 0);  // root bone index
    append_varint(bytes, 1);  // root timeline count
    bytes.push_back(0);       // rotate timeline
    append_varint(bytes, 2);  // frames
    append_float(bytes, 0.0f);
    append_float(bytes, 0.0f);
    bytes.push_back(0);  // linear curve
    append_float(bytes, 1.25f);
    append_float(bytes, 0.0f);

    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
    return bytes;
}

std::vector<uint8_t> make_region_skeleton() {
    std::vector<uint8_t> bytes;

    append_string(bytes, "region-contract-fixture");
    append_string(bytes, "3.8.99");
    append_float(bytes, -2.0f);
    append_float(bytes, 3.0f);
    append_float(bytes, 4.0f);
    append_float(bytes, 5.0f);
    bytes.push_back(0);  // nonessential

    append_varint(bytes, 2);  // string table
    append_string(bytes, "fixture-skin");
    append_string(bytes, "fixture-region");

    append_varint(bytes, 1);  // bones
    append_string(bytes, "root");
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(0);         // skin required

    append_varint(bytes, 1);  // slots
    append_string(bytes, "region-slot");
    append_varint(bytes, 0);  // root bone
    append_color(bytes, 128, 192, 255, 128);
    append_color(bytes, 255, 255, 255, 255);  // no dark color
    append_varint(bytes, 2);                    // setup attachment
    append_varint(bytes, 0);                    // normal blend

    append_varint(bytes, 0);  // IK constraints
    append_varint(bytes, 0);  // transform constraints
    append_varint(bytes, 0);  // path constraints

    append_varint(bytes, 1);  // default skin slots
    append_varint(bytes, 0);  // slot index
    append_varint(bytes, 1);  // attachments in slot
    append_varint(bytes, 2);  // attachment key
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(0);       // region attachment
    append_varint(bytes, 0);  // path uses name
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 2.0f);  // x
    append_float(bytes, 3.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 2.0f);  // width
    append_float(bytes, 4.0f);  // height
    append_color(bytes, 128, 255, 64, 128);

    append_varint(bytes, 1);  // additional skins
    append_varint(bytes, 1);  // fixture-skin
    append_varint(bytes, 0);  // skin bones
    append_varint(bytes, 0);  // skin IK constraints
    append_varint(bytes, 0);  // skin transform constraints
    append_varint(bytes, 0);  // skin path constraints
    append_varint(bytes, 0);  // skin slots

    append_varint(bytes, 0);  // events
    append_varint(bytes, 1);  // animations
    append_string(bytes, animation_name_fixture);
    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 1);  // bone timeline groups
    append_varint(bytes, 0);  // root bone index
    append_varint(bytes, 1);  // root timeline count
    bytes.push_back(0);       // rotate timeline
    append_varint(bytes, 2);  // frames
    append_float(bytes, 0.0f);
    append_float(bytes, 0.0f);
    bytes.push_back(0);  // linear curve
    append_float(bytes, 1.25f);
    append_float(bytes, 90.0f);
    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
    return bytes;
}

void append_region_attachment(
    std::vector<uint8_t>& bytes,
    float x,
    float y) {
    append_varint(bytes, 2);  // attachment key
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(0);       // region attachment
    append_varint(bytes, 0);  // path uses name
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, x);
    append_float(bytes, y);
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 2.0f);  // width
    append_float(bytes, 2.0f);  // height
    append_color(bytes, 255, 255, 255, 255);
}

void append_mesh_attachment(
    std::vector<uint8_t>& bytes,
    uint32_t attachment_key = 2u,
    uint16_t third_triangle_index = 2u,
    size_t triangle_repetitions = 1u,
    uint32_t vertex_count = 3u) {
    append_varint(bytes, attachment_key);
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(2);       // mesh attachment
    append_varint(bytes, 0);  // path uses name
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, vertex_count);
    for (uint32_t vertex = 0u; vertex < vertex_count; ++vertex) {
        append_float(bytes, vertex == 1u ? 1.0f : 0.0f);
        append_float(bytes, vertex == 2u ? 1.0f : 0.0f);
    }
    append_varint(
        bytes, static_cast<uint32_t>(triangle_repetitions * 3u));
    for (size_t triangle = 0u; triangle < triangle_repetitions; ++triangle) {
        bytes.push_back(0);
        bytes.push_back(0);
        bytes.push_back(0);
        bytes.push_back(1);
        bytes.push_back(
            static_cast<uint8_t>((third_triangle_index >> 8u) & 0xffu));
        bytes.push_back(static_cast<uint8_t>(third_triangle_index & 0xffu));
    }
    bytes.push_back(0);  // unweighted vertices
    for (uint32_t vertex = 0u; vertex < vertex_count; ++vertex) {
        append_float(bytes, vertex == 1u ? 2.0f : 0.0f);
        append_float(bytes, vertex == 2u ? 2.0f : 0.0f);
    }
    append_varint(bytes, 3);  // hull vertex count
}

std::vector<uint8_t> make_mesh_blend_skeleton() {
    std::vector<uint8_t> bytes;
    append_string(bytes, "mesh-blend-contract-fixture");
    append_string(bytes, "3.8.99");
    append_float(bytes, -2.0f);
    append_float(bytes, 3.0f);
    append_float(bytes, 4.0f);
    append_float(bytes, 5.0f);
    bytes.push_back(0);  // nonessential

    append_varint(bytes, 2);  // string table
    append_string(bytes, "fixture-skin");
    append_string(bytes, "fixture-region");

    append_varint(bytes, 1);  // bones
    append_string(bytes, "root");
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(0);         // skin required

    append_varint(bytes, 5);  // slots
    for (uint32_t slot = 0u; slot < 5u; ++slot) {
        append_string(bytes, "draw-slot-" + std::to_string(slot));
        append_varint(bytes, 0);  // root bone
        append_color(bytes, 255, 255, 255, 255);
        append_color(bytes, 255, 255, 255, 255);  // no dark color
        append_varint(bytes, 2);                   // setup attachment
        append_varint(bytes, slot < 4u ? slot : 0u);
    }

    append_varint(bytes, 0);  // IK constraints
    append_varint(bytes, 0);  // transform constraints
    append_varint(bytes, 0);  // path constraints

    append_varint(bytes, 5);  // default skin slots
    for (uint32_t slot = 0u; slot < 4u; ++slot) {
        append_varint(bytes, slot);
        append_varint(bytes, 1);  // attachments in slot
        append_region_attachment(bytes, static_cast<float>(slot * 3u), 0.0f);
    }
    append_varint(bytes, 4);  // mesh slot
    append_varint(bytes, 1);  // attachments in slot
    append_mesh_attachment(bytes);

    append_varint(bytes, 0);  // additional skins
    append_varint(bytes, 0);  // events
    append_varint(bytes, 1);  // animations
    append_string(bytes, animation_name_fixture);
    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 1);  // bone timeline groups
    append_varint(bytes, 0);  // root bone index
    append_varint(bytes, 1);  // root timeline count
    bytes.push_back(0);       // rotate timeline
    append_varint(bytes, 2);  // frames
    append_float(bytes, 0.0f);
    append_float(bytes, 0.0f);
    bytes.push_back(0);  // linear curve
    append_float(bytes, 1.25f);
    append_float(bytes, 0.0f);
    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
    return bytes;
}

std::vector<uint8_t> make_clipping_skeleton(
    bool unsupported_attachment,
    float region_x = 0.0f,
    bool mesh_attachment = false,
    uint16_t mesh_third_triangle_index = 2u,
    size_t mesh_triangle_repetitions = 1u,
    float clip_extent = 0.5f,
    uint32_t mesh_vertex_count = 3u,
    uint32_t clip_vertex_count = 4u) {
    std::vector<uint8_t> bytes;
    append_string(bytes, "clipping-contract-fixture");
    append_string(bytes, "3.8.99");
    append_float(bytes, -2.0f);
    append_float(bytes, -2.0f);
    append_float(bytes, 4.0f);
    append_float(bytes, 4.0f);
    bytes.push_back(0);  // nonessential

    append_varint(bytes, 2);  // string table
    append_string(bytes, "fixture-region");
    append_string(bytes, "fixture-clip");

    append_varint(bytes, 1);  // bones
    append_string(bytes, "root");
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(0);         // skin required

    append_varint(bytes, 2);  // slots
    append_string(bytes, "clip-slot");
    append_varint(bytes, 0);
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 2);  // fixture-clip
    append_varint(bytes, 0);  // normal blend
    append_string(bytes, "region-slot");
    append_varint(bytes, 0);
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 1);  // fixture-region
    append_varint(bytes, 0);  // normal blend

    append_varint(bytes, 0);  // IK constraints
    append_varint(bytes, 0);  // transform constraints
    append_varint(bytes, 0);  // path constraints

    append_varint(bytes, 2);  // default skin slots
    append_varint(bytes, 0);  // clip slot
    append_varint(bytes, 1);  // attachments in slot
    append_varint(bytes, 2);  // fixture-clip key
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(unsupported_attachment ? 1u : 6u);
    if (!unsupported_attachment) {
        append_varint(bytes, 1);  // clipping ends after region slot
    }
    append_varint(bytes, clip_vertex_count);
    bytes.push_back(0);       // unweighted vertices
    constexpr float x_signs[] = {-1.0f, -1.0f, 1.0f, 1.0f};
    constexpr float y_signs[] = {-1.0f, 1.0f, 1.0f, -1.0f};
    for (uint32_t vertex = 0u; vertex < clip_vertex_count; ++vertex) {
        append_float(bytes, x_signs[vertex % 4u] * clip_extent);
        append_float(bytes, y_signs[vertex % 4u] * clip_extent);
    }

    append_varint(bytes, 1);  // region slot
    append_varint(bytes, 1);  // attachments in slot
    if (mesh_attachment) {
        append_mesh_attachment(
            bytes, 1u, mesh_third_triangle_index,
            mesh_triangle_repetitions, mesh_vertex_count);
    } else {
        append_varint(bytes, 1);  // fixture-region key
        append_varint(bytes, 0);  // attachment name uses key
        bytes.push_back(0);       // region attachment
        append_varint(bytes, 0);  // path uses name
        append_float(bytes, 0.0f);  // rotation
        append_float(bytes, region_x);
        append_float(bytes, 0.0f);  // y
        append_float(bytes, 1.0f);  // scale x
        append_float(bytes, 1.0f);  // scale y
        append_float(bytes, 2.0f);  // width
        append_float(bytes, 2.0f);  // height
        append_color(bytes, 255, 255, 255, 255);
    }

    append_varint(bytes, 0);  // additional skins
    append_varint(bytes, 0);  // events
    append_varint(bytes, 1);  // animations
    append_string(bytes, animation_name_fixture);
    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 1);  // bone timeline groups
    append_varint(bytes, 0);  // root bone index
    append_varint(bytes, 1);  // root timeline count
    bytes.push_back(0);       // rotate timeline
    append_varint(bytes, 2);  // frames
    append_float(bytes, 0.0f);
    append_float(bytes, 0.0f);
    bytes.push_back(0);  // linear curve
    append_float(bytes, 1.25f);
    append_float(bytes, 0.0f);
    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
    return bytes;
}

std::vector<uint8_t> make_malformed_clipping_skeleton(
    uint32_t clip_vertex_count) {
    return make_clipping_skeleton(
        false, 0.0f, false, 2u, 1u, 0.5f, 3u, clip_vertex_count);
}

std::vector<uint8_t> make_inactive_bone_skeleton() {
    std::vector<uint8_t> bytes;
    append_string(bytes, "inactive-bone-contract-fixture");
    append_string(bytes, "3.8.99");
    append_float(bytes, -2.0f);
    append_float(bytes, -2.0f);
    append_float(bytes, 8.0f);
    append_float(bytes, 4.0f);
    bytes.push_back(0);  // nonessential

    append_varint(bytes, 2);  // string table
    append_string(bytes, "fixture-clip");
    append_string(bytes, "fixture-region");

    append_varint(bytes, 2);  // bones
    append_string(bytes, "root");
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(0);         // skin required
    append_string(bytes, "inactive-child");
    append_varint(bytes, 0);    // root parent
    append_float(bytes, 0.0f);  // rotation
    append_float(bytes, 0.0f);  // x
    append_float(bytes, 0.0f);  // y
    append_float(bytes, 1.0f);  // scale x
    append_float(bytes, 1.0f);  // scale y
    append_float(bytes, 0.0f);  // shear x
    append_float(bytes, 0.0f);  // shear y
    append_float(bytes, 0.0f);  // length
    append_varint(bytes, 0);    // transform mode
    bytes.push_back(1);         // skin required and absent from current skin

    append_varint(bytes, 4);  // slots
    append_string(bytes, "clip-slot");
    append_varint(bytes, 0);  // root bone
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 1);  // fixture-clip
    append_varint(bytes, 0);  // normal blend
    append_string(bytes, "inactive-end-region-slot");
    append_varint(bytes, 1);  // inactive child bone
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 2);  // fixture-region
    append_varint(bytes, 0);  // normal blend
    append_string(bytes, "inactive-unsupported-slot");
    append_varint(bytes, 1);  // inactive child bone
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 1);  // fixture-clip
    append_varint(bytes, 0);  // normal blend
    append_string(bytes, "active-region-slot");
    append_varint(bytes, 0);  // root bone
    append_color(bytes, 255, 255, 255, 255);
    append_color(bytes, 255, 255, 255, 255);
    append_varint(bytes, 2);  // fixture-region
    append_varint(bytes, 0);  // normal blend

    append_varint(bytes, 0);  // IK constraints
    append_varint(bytes, 0);  // transform constraints
    append_varint(bytes, 0);  // path constraints

    append_varint(bytes, 4);  // default skin slots
    append_varint(bytes, 0);  // clip slot
    append_varint(bytes, 1);  // attachments in slot
    append_varint(bytes, 1);  // fixture-clip key
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(6);       // clipping attachment
    append_varint(bytes, 1);  // ends at inactive region slot
    append_varint(bytes, 4);  // polygon vertex count
    bytes.push_back(0);       // unweighted vertices
    append_float(bytes, -0.5f);
    append_float(bytes, -0.5f);
    append_float(bytes, -0.5f);
    append_float(bytes, 0.5f);
    append_float(bytes, 0.5f);
    append_float(bytes, 0.5f);
    append_float(bytes, 0.5f);
    append_float(bytes, -0.5f);

    append_varint(bytes, 1);  // inactive region slot
    append_varint(bytes, 1);  // attachments in slot
    append_region_attachment(bytes, 0.0f, 0.0f);

    append_varint(bytes, 2);  // inactive unsupported slot
    append_varint(bytes, 1);  // attachments in slot
    append_varint(bytes, 1);  // fixture-clip key
    append_varint(bytes, 0);  // attachment name uses key
    bytes.push_back(1);       // bounding box attachment
    append_varint(bytes, 3);  // vertex count
    bytes.push_back(0);       // unweighted vertices
    append_float(bytes, -1.0f);
    append_float(bytes, -1.0f);
    append_float(bytes, 0.0f);
    append_float(bytes, 1.0f);
    append_float(bytes, 1.0f);
    append_float(bytes, -1.0f);

    append_varint(bytes, 3);  // active region slot
    append_varint(bytes, 1);  // attachments in slot
    append_region_attachment(bytes, 4.0f, 0.0f);

    append_varint(bytes, 0);  // additional skins
    append_varint(bytes, 0);  // events
    append_varint(bytes, 1);  // animations
    append_string(bytes, animation_name_fixture);
    append_varint(bytes, 0);  // slot timelines
    append_varint(bytes, 1);  // bone timeline groups
    append_varint(bytes, 0);  // root bone index
    append_varint(bytes, 1);  // root timeline count
    bytes.push_back(0);       // rotate timeline
    append_varint(bytes, 2);  // frames
    append_float(bytes, 0.0f);
    append_float(bytes, 0.0f);
    bytes.push_back(0);  // linear curve
    append_float(bytes, 1.25f);
    append_float(bytes, 0.0f);
    append_varint(bytes, 0);  // IK timelines
    append_varint(bytes, 0);  // transform timelines
    append_varint(bytes, 0);  // path timelines
    append_varint(bytes, 0);  // deform timelines
    append_varint(bytes, 0);  // draw-order timeline frames
    append_varint(bytes, 0);  // event timeline frames
    return bytes;
}

constexpr char atlas_fixture[] =
    "fixture-page.png\n"
    "size: 1,1\n"
    "format: RGBA8888\n"
    "filter: Nearest,Nearest\n"
    "repeat: none\n";

constexpr char region_atlas_fixture[] =
    "fixture-page.png\n"
    "size: 8,8\n"
    "format: RGBA8888\n"
    "filter: Nearest,Nearest\n"
    "repeat: none\n"
    "fixture-region\n"
    "  rotate: false\n"
    "  xy: 0,0\n"
    "  size: 2,4\n"
    "  orig: 2,4\n"
    "  offset: 0,0\n"
    "  index: -1\n";

void check_atlas_leading_whitespace_contract() {
    const auto skeleton = make_synthetic_skeleton();
    const std::vector<std::string> valid_atlases{
        std::string("\n") + atlas_fixture,
        std::string(" \t\r\n\r\n\t \n") + atlas_fixture,
    };

    for (const std::string& atlas : valid_atlases) {
        ArkClawSpine38Handle* handle = nullptr;
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas.data(), atlas.size(),
                  &handle) == ARKCLAW_SPINE38_OK);
        CHECK(handle != nullptr);
        if (handle != nullptr) {
            CHECK(arkclaw_spine38_animation_count(handle) == 1u);
            arkclaw_spine38_destroy(handle);
        }
    }

    const std::vector<std::string> invalid_atlases{
        " \t\r\n\r\n\t \n",
        "\nfixture-page.png\nsize: 1,1\nformat: RGBA8888\n",
    };
    for (const std::string& atlas : invalid_atlases) {
        ArkClawSpine38Handle* handle = reinterpret_cast<
            ArkClawSpine38Handle*>(static_cast<uintptr_t>(1));
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas.data(), atlas.size(),
                  &handle) == ARKCLAW_SPINE38_ATLAS_LOAD_FAILED);
        CHECK(handle == nullptr);
    }
}

void check_fixed_contract_values() {
    CHECK(arkclaw_spine38_abi_version() == 1u);
    CHECK(ARKCLAW_SPINE38_OK == 0);
    CHECK(ARKCLAW_SPINE38_INVALID_ARGUMENT == 1);
    CHECK(ARKCLAW_SPINE38_ATLAS_LOAD_FAILED == 2);
    CHECK(ARKCLAW_SPINE38_SKELETON_LOAD_FAILED == 3);
    CHECK(ARKCLAW_SPINE38_ANIMATION_NOT_FOUND == 4);
    CHECK(ARKCLAW_SPINE38_RUNTIME_FAILURE == 5);
    CHECK(ARKCLAW_SPINE38_FILTER_UNKNOWN == 0);
    CHECK(ARKCLAW_SPINE38_FILTER_NEAREST == 1);
    CHECK(ARKCLAW_SPINE38_FILTER_LINEAR == 2);
}

void check_texture_filter_metadata() {
    const auto skeleton = make_synthetic_skeleton();
    const struct FilterCase {
        const char* declaration;
        uint32_t expected_min;
        uint32_t expected_mag;
    } cases[]{
        {"Nearest,Nearest", 1u, 1u},
        {"Nearest,Linear", 1u, 2u},
        {"Linear,Nearest", 2u, 1u},
        {"Linear,Linear", 2u, 2u},
    };
    for (const FilterCase& item : cases) {
        const std::string atlas =
            std::string("fixture-page.png\nsize: 1,1\nformat: RGBA8888\nfilter: ") +
            item.declaration + "\nrepeat: none\n";
        ArkClawSpine38Handle* handle = nullptr;
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas.data(), atlas.size(),
                  &handle) == ARKCLAW_SPINE38_OK);
        ArkClawSpine38TexturePageView view{99u, 98u};
        CHECK(arkclaw_spine38_texture_page_view(
                  handle, &view, sizeof(view)) == ARKCLAW_SPINE38_OK);
        CHECK(view.min_filter == item.expected_min);
        CHECK(view.mag_filter == item.expected_mag);
        ArkClawSpine38TexturePageView sentinel{91u, 92u};
        CHECK(arkclaw_spine38_texture_page_view(
                  handle, &sentinel, sizeof(sentinel) - 1u) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(sentinel.min_filter == 91u);
        CHECK(sentinel.mag_filter == 92u);
        arkclaw_spine38_destroy(handle);
    }
}

void check_zero_duration_animation_is_not_exposed() {
    const auto skeleton = make_synthetic_skeleton(true);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_animation_count(handle) == 1u);
    const size_t capacity = arkclaw_spine38_animation_name_size(handle, 0);
    CHECK(capacity == sizeof(animation_name_fixture));
    std::vector<char> name(capacity, '#');
    float duration = -1.0f;
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, name.data(), name.size(), &duration) ==
          ARKCLAW_SPINE38_OK);
    CHECK(std::memcmp(
              name.data(), animation_name_fixture,
              sizeof(animation_name_fixture)) == 0);
    CHECK(duration == 1.25f);
    CHECK(arkclaw_spine38_animation_name_size(handle, 1) == 0u);
    arkclaw_spine38_destroy(handle);
}

void check_playback_contract_without_drawables() {
    const auto skeleton = make_synthetic_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    const char animation_name[] = "idle-\xE7\x8C\xAB";
    const char embedded_nul[] = {'i', 'd', '\0', 'l', 'e'};
    ArkClawSpine38DrawView sentinel{
        reinterpret_cast<const ArkClawSpine38Vertex*>(
            static_cast<uintptr_t>(1)),
        11u,
        reinterpret_cast<const uint32_t*>(static_cast<uintptr_t>(2)),
        12u,
        13u,
        14u,
        15};

    CHECK(arkclaw_spine38_draw_count(nullptr) == 0u);
    CHECK(arkclaw_spine38_set_animation(
              nullptr, 0u, animation_name, sizeof(animation_name) - 1u, 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, nullptr, sizeof(animation_name) - 1u, 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name, 0u, 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, embedded_nul, sizeof(embedded_nul), 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, "missing", sizeof("missing") - 1u, 1u) ==
          ARKCLAW_SPINE38_ANIMATION_NOT_FOUND);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name, sizeof(animation_name) - 1u, 2u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name, sizeof(animation_name) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);

    CHECK(arkclaw_spine38_update(nullptr, 0.0f) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_update(handle, -0.01f) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_update(
              handle, std::numeric_limits<float>::infinity()) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_update(
              handle, std::numeric_limits<float>::quiet_NaN()) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_update(handle, 0.0f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);

    CHECK(arkclaw_spine38_draw_view(
              nullptr, 0u, &sentinel, sizeof(sentinel)) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(sentinel.vertex_count == 11u);
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, nullptr, sizeof(sentinel)) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &sentinel, sizeof(sentinel) - 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(sentinel.vertex_count == 11u);
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &sentinel, sizeof(sentinel)) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(sentinel.vertex_count == 11u);

    arkclaw_spine38_destroy(handle);
}

void check_track_zero_event_contract() {
    const auto skeleton = make_synthetic_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_event_count(nullptr) == 0u);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);

    for (uint64_t ordinal = 1u; ordinal <= 3u; ++ordinal) {
        CHECK(arkclaw_spine38_update(handle, 1.0f) == ARKCLAW_SPINE38_OK);
        CHECK(arkclaw_spine38_event_count(handle) == 0u);
        CHECK(arkclaw_spine38_update(handle, 0.3f) == ARKCLAW_SPINE38_OK);
        CHECK(arkclaw_spine38_event_count(handle) == 1u);
        ArkClawSpine38EventView view{};
        CHECK(arkclaw_spine38_event_view(
                  handle, 0u, &view, sizeof(view)) == ARKCLAW_SPINE38_OK);
        CHECK(view.event_type == ARKCLAW_SPINE38_EVENT_LOOP_BOUNDARY);
        CHECK(view.track == 0u);
        CHECK(view.loop_ordinal == ordinal);
        CHECK(view.animation_name_size == sizeof(animation_name_fixture) - 1u);
        CHECK(view.animation_name_utf8 != nullptr);
        if (view.animation_name_utf8 != nullptr) {
            CHECK(std::memcmp(
                      view.animation_name_utf8, animation_name_fixture,
                      view.animation_name_size) == 0);
        }
    }

    ArkClawSpine38EventView sentinel{
        7u,
        8u,
        9u,
        reinterpret_cast<const char*>(static_cast<uintptr_t>(1)),
        10u};
    CHECK(arkclaw_spine38_event_view(
              handle, 0u, &sentinel, sizeof(sentinel) - 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(sentinel.event_type == 7u);
    CHECK(sentinel.loop_ordinal == 9u);

    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 0u) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_mix_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 0u, 0.12f) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_mix_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 0u, -0.01f) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(arkclaw_spine38_event_count(handle) == 0u);
    CHECK(arkclaw_spine38_update(handle, 1.25f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_event_count(handle) == 1u);
    ArkClawSpine38EventView completion{};
    CHECK(arkclaw_spine38_event_view(
              handle, 0u, &completion, sizeof(completion)) ==
          ARKCLAW_SPINE38_OK);
    CHECK(completion.event_type == ARKCLAW_SPINE38_EVENT_COMPLETE);
    CHECK(completion.loop_ordinal == 0u);

    CHECK(arkclaw_spine38_clear_track(handle, 0u) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_event_count(handle) == 0u);
    CHECK(arkclaw_spine38_update(handle, 1.25f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_event_count(handle) == 0u);
    CHECK(arkclaw_spine38_clear_track(nullptr, 0u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);

    arkclaw_spine38_destroy(handle);
}

void check_region_draw_view_is_materialized() {
    const auto skeleton = make_region_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_update(handle, 0.0f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 1u);
    CHECK(arkclaw_spine38_mix_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u, 0.12f) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 1u);

    ArkClawSpine38DrawView view{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &view, sizeof(view)) == ARKCLAW_SPINE38_OK);
    CHECK(view.vertices != nullptr);
    CHECK(view.vertex_count == 4u);
    CHECK(view.indices != nullptr);
    CHECK(view.index_count == 6u);
    CHECK(view.texture_page == 0u);
    CHECK(view.blend_mode == ARKCLAW_SPINE38_BLEND_NORMAL);
    CHECK(view.draw_order == 0);
    if (view.vertices != nullptr && view.vertex_count == 4u) {
        float min_x = view.vertices[0].x;
        float max_x = view.vertices[0].x;
        float min_y = view.vertices[0].y;
        float max_y = view.vertices[0].y;
        for (size_t index = 0u; index < view.vertex_count; ++index) {
            const ArkClawSpine38Vertex& vertex = view.vertices[index];
            CHECK(std::isfinite(vertex.x));
            CHECK(std::isfinite(vertex.y));
            CHECK(std::isfinite(vertex.u));
            CHECK(std::isfinite(vertex.v));
            CHECK(vertex.r == 64u);
            CHECK(vertex.g == 192u);
            CHECK(vertex.b == 64u);
            CHECK(vertex.a == 64u);
            min_x = vertex.x < min_x ? vertex.x : min_x;
            max_x = vertex.x > max_x ? vertex.x : max_x;
            min_y = vertex.y < min_y ? vertex.y : min_y;
            max_y = vertex.y > max_y ? vertex.y : max_y;
        }
        CHECK(std::fabs(min_x - 1.0f) < 0.00001f);
        CHECK(std::fabs(max_x - 3.0f) < 0.00001f);
        CHECK(std::fabs(min_y - 1.0f) < 0.00001f);
        CHECK(std::fabs(max_y - 5.0f) < 0.00001f);
    }
    if (view.indices != nullptr && view.index_count == 6u) {
        const uint32_t expected[] = {0u, 1u, 2u, 2u, 3u, 0u};
        CHECK(std::memcmp(view.indices, expected, sizeof(expected)) == 0);
    }

    ArkClawSpine38DrawView repeated{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &repeated, sizeof(repeated)) ==
          ARKCLAW_SPINE38_OK);
    CHECK(repeated.vertices == view.vertices);
    CHECK(repeated.indices == view.indices);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, "missing", sizeof("missing") - 1u, 1u) ==
          ARKCLAW_SPINE38_ANIMATION_NOT_FOUND);
    ArkClawSpine38DrawView after_failed_set{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &after_failed_set, sizeof(after_failed_set)) ==
          ARKCLAW_SPINE38_OK);
    CHECK(after_failed_set.vertices == view.vertices);
    CHECK(after_failed_set.indices == view.indices);

    float setup_positions[8]{};
    if (view.vertices != nullptr && view.vertex_count == 4u) {
        for (size_t index = 0u; index < view.vertex_count; ++index) {
            setup_positions[index * 2u] = view.vertices[index].x;
            setup_positions[index * 2u + 1u] = view.vertices[index].y;
        }
    }
    CHECK(arkclaw_spine38_update(handle, 0.625f) == ARKCLAW_SPINE38_OK);
    ArkClawSpine38DrawView animated{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &animated, sizeof(animated)) ==
          ARKCLAW_SPINE38_OK);
    bool geometry_changed = false;
    if (animated.vertices != nullptr && animated.vertex_count == 4u) {
        for (size_t index = 0u; index < animated.vertex_count; ++index) {
            const float x_change = std::fabs(
                animated.vertices[index].x - setup_positions[index * 2u]);
            const float y_change = std::fabs(
                animated.vertices[index].y -
                setup_positions[index * 2u + 1u]);
            geometry_changed = geometry_changed || x_change > 0.00001f ||
                               y_change > 0.00001f;
        }
    }
    CHECK(geometry_changed);
    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);

    arkclaw_spine38_destroy(handle);
}

void check_mesh_blend_modes_and_draw_order_are_materialized() {
    const auto skeleton = make_mesh_blend_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_update(handle, 0.5f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 5u);

    const uint32_t expected_blends[] = {
        ARKCLAW_SPINE38_BLEND_NORMAL,
        ARKCLAW_SPINE38_BLEND_ADDITIVE,
        ARKCLAW_SPINE38_BLEND_MULTIPLY,
        ARKCLAW_SPINE38_BLEND_SCREEN,
        ARKCLAW_SPINE38_BLEND_NORMAL};
    for (size_t index = 0u; index < 5u; ++index) {
        ArkClawSpine38DrawView view{};
        CHECK(arkclaw_spine38_draw_view(
                  handle, index, &view, sizeof(view)) ==
              ARKCLAW_SPINE38_OK);
        CHECK(view.texture_page == 0u);
        CHECK(view.blend_mode == expected_blends[index]);
        CHECK(view.draw_order == static_cast<int32_t>(index));
        CHECK(view.vertices != nullptr);
        CHECK(view.indices != nullptr);
        if (view.indices != nullptr) {
            for (size_t triangle_index = 0u;
                 triangle_index < view.index_count;
                 ++triangle_index) {
                CHECK(view.indices[triangle_index] < view.vertex_count);
            }
        }
        if (index < 4u) {
            CHECK(view.vertex_count == 4u);
            CHECK(view.index_count == 6u);
        } else {
            CHECK(view.vertex_count == 3u);
            CHECK(view.index_count == 3u);
            if (view.vertices != nullptr && view.vertex_count == 3u) {
                CHECK(std::fabs(view.vertices[0].x - 0.0f) < 0.00001f);
                CHECK(std::fabs(view.vertices[0].y - 0.0f) < 0.00001f);
                CHECK(std::fabs(view.vertices[1].x - 2.0f) < 0.00001f);
                CHECK(std::fabs(view.vertices[1].y - 0.0f) < 0.00001f);
                CHECK(std::fabs(view.vertices[2].x - 0.0f) < 0.00001f);
                CHECK(std::fabs(view.vertices[2].y - 2.0f) < 0.00001f);
            }
        }
    }

    arkclaw_spine38_destroy(handle);
}

void check_clipping_is_applied_inside_the_abi() {
    const auto skeleton = make_clipping_skeleton(false);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_set_animation(
              handle, 0u, animation_name_fixture,
              sizeof(animation_name_fixture) - 1u, 1u) ==
          ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_update(handle, 0.0f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 1u);
    ArkClawSpine38DrawView view{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &view, sizeof(view)) == ARKCLAW_SPINE38_OK);
    CHECK(view.draw_order == 1);
    CHECK(view.vertices != nullptr);
    CHECK(view.vertex_count > 0u);
    CHECK(view.indices != nullptr);
    CHECK(view.index_count > 0u);
    CHECK((view.index_count % 3u) == 0u);
    if (view.vertices != nullptr) {
        for (size_t index = 0u; index < view.vertex_count; ++index) {
            CHECK(view.vertices[index].x >= -0.50001f);
            CHECK(view.vertices[index].x <= 0.50001f);
            CHECK(view.vertices[index].y >= -0.50001f);
            CHECK(view.vertices[index].y <= 0.50001f);
        }
    }
    if (view.indices != nullptr) {
        for (size_t index = 0u; index < view.index_count; ++index) {
            CHECK(view.indices[index] < view.vertex_count);
        }
    }
    arkclaw_spine38_destroy(handle);
}

void check_malformed_clipped_mesh_index_fails_closed() {
    const auto skeleton = make_clipping_skeleton(
        false, 0.0f, true, 32768u, 1u, 1.0e15f, 32768u);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_update(handle, 0.0f) ==
          ARKCLAW_SPINE38_RUNTIME_FAILURE);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);
    arkclaw_spine38_destroy(handle);
}

void check_unrepresentable_clipped_mesh_fails_closed() {
    constexpr size_t triangle_repetitions = 21846u;
    const auto skeleton = make_clipping_skeleton(
        false, 0.0f, true, 2u, triangle_repetitions, 1.0e15f);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_update(handle, 0.0f) ==
          ARKCLAW_SPINE38_RUNTIME_FAILURE);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);
    arkclaw_spine38_destroy(handle);
}

void check_malformed_clipping_polygon_fails_closed() {
    for (uint32_t clip_vertex_count : {0u, 1u, 2u}) {
        const auto skeleton =
            make_malformed_clipping_skeleton(clip_vertex_count);
        ArkClawSpine38Handle* handle = nullptr;
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), region_atlas_fixture,
                  sizeof(region_atlas_fixture) - 1u, &handle) ==
              ARKCLAW_SPINE38_OK);
        CHECK(handle != nullptr);
        if (handle == nullptr) {
            continue;
        }

        CHECK(arkclaw_spine38_update(handle, 0.0f) ==
              ARKCLAW_SPINE38_RUNTIME_FAILURE);
        CHECK(arkclaw_spine38_draw_count(handle) == 0u);
        arkclaw_spine38_destroy(handle);
    }
}

void check_inactive_bone_slots_are_skipped_and_end_clipping() {
    const auto skeleton = make_inactive_bone_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_update(handle, 0.0f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 1u);
    ArkClawSpine38DrawView view{};
    CHECK(arkclaw_spine38_draw_view(
              handle, 0u, &view, sizeof(view)) == ARKCLAW_SPINE38_OK);
    CHECK(view.draw_order == 3);
    CHECK(view.vertex_count == 4u);
    CHECK(view.index_count == 6u);
    if (view.vertices != nullptr && view.vertex_count == 4u) {
        for (size_t vertex = 0u; vertex < view.vertex_count; ++vertex) {
            CHECK(view.vertices[vertex].x >= 2.99999f);
            CHECK(view.vertices[vertex].x <= 5.00001f);
        }
    }
    arkclaw_spine38_destroy(handle);
}

void check_unsupported_active_attachment_fails_closed() {
    const auto skeleton = make_clipping_skeleton(true);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }
    CHECK(arkclaw_spine38_update(handle, 0.0f) ==
          ARKCLAW_SPINE38_RUNTIME_FAILURE);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);
    arkclaw_spine38_destroy(handle);
}

void check_fully_clipped_attachment_is_a_valid_empty_draw() {
    const auto skeleton = make_clipping_skeleton(false, 3.0f);
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), region_atlas_fixture,
              sizeof(region_atlas_fixture) - 1u, &handle) ==
          ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }
    CHECK(arkclaw_spine38_update(handle, 0.0f) == ARKCLAW_SPINE38_OK);
    CHECK(arkclaw_spine38_draw_count(handle) == 0u);
    arkclaw_spine38_destroy(handle);
}

void check_invalid_inputs_do_not_escape_exceptions() {
    ArkClawSpine38Handle* handle = reinterpret_cast<ArkClawSpine38Handle*>(
        static_cast<uintptr_t>(1));
    const auto skeleton = make_synthetic_skeleton();
    const uint8_t nonnull_byte = 0;

    try {
        CHECK(arkclaw_spine38_create(
                  nullptr, 0, nullptr, 0, &handle) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        const size_t oversized_span =
            static_cast<size_t>(std::numeric_limits<int>::max()) + 1u;
        handle = reinterpret_cast<ArkClawSpine38Handle*>(
            static_cast<uintptr_t>(1));
        CHECK(arkclaw_spine38_create(
                  &nonnull_byte, oversized_span, atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);
        handle = reinterpret_cast<ArkClawSpine38Handle*>(
            static_cast<uintptr_t>(1));
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture,
                  oversized_span, &handle) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        CHECK(arkclaw_spine38_create(
                  &nonnull_byte, 0, atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);
        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture, 0,
                  &handle) == ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture,
                  sizeof(atlas_fixture) - 1u, nullptr) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);

        CHECK(arkclaw_spine38_create(
                  skeleton.data(), skeleton.size(), "not-an-atlas", 12,
                  &handle) == ARKCLAW_SPINE38_ATLAS_LOAD_FAILED);
        CHECK(handle == nullptr);

        const uint8_t invalid_skeleton[] = {0};
        CHECK(arkclaw_spine38_create(
                  invalid_skeleton, sizeof(invalid_skeleton), atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              ARKCLAW_SPINE38_SKELETON_LOAD_FAILED);
        CHECK(handle == nullptr);

        CHECK(arkclaw_spine38_animation_count(nullptr) == 0u);
        CHECK(arkclaw_spine38_animation_name_size(nullptr, 0) == 0u);
        CHECK(arkclaw_spine38_skin_count(nullptr) == 0u);
        CHECK(arkclaw_spine38_skin_name_size(nullptr, 0) == 0u);

        char name[8] = {'#', '#', '#', '#', '#', '#', '#', '#'};
        float duration = -1.0f;
        CHECK(arkclaw_spine38_animation_info(
                  nullptr, 0, name, sizeof(name), &duration) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(name[0] == '#');
        CHECK(duration == -1.0f);
        CHECK(arkclaw_spine38_skin_info(
                  nullptr, 0, name, sizeof(name)) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(name[0] == '#');
        ArkClawSpine38Bounds bounds{-1.0f, -2.0f, -3.0f, -4.0f};
        CHECK(arkclaw_spine38_setup_bounds(nullptr, &bounds) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(bounds.x == -1.0f);
        CHECK(bounds.y == -2.0f);
        CHECK(bounds.width == -3.0f);
        CHECK(bounds.height == -4.0f);
        ArkClawSpine38RootTransform root{-5.0f, -6.0f};
        CHECK(arkclaw_spine38_root_transform(nullptr, &root) ==
              ARKCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(root.x == -5.0f);
        CHECK(root.y == -6.0f);

        arkclaw_spine38_destroy(nullptr);
        arkclaw_spine38_destroy(nullptr);
    } catch (...) {
        CHECK(false);
    }
}

void check_synthetic_catalog_and_buffers() {
    const auto skeleton = make_synthetic_skeleton();
    ArkClawSpine38Handle* handle = nullptr;
    CHECK(arkclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == ARKCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(arkclaw_spine38_animation_count(handle) == 1u);
    const size_t animation_capacity =
        arkclaw_spine38_animation_name_size(handle, 0);
    CHECK(animation_capacity == sizeof(animation_name_fixture));

    float duration = -7.0f;
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, nullptr, animation_capacity, &duration) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(duration == -7.0f);

    std::vector<char> zero_capacity(animation_capacity, '#');
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, zero_capacity.data(), 0, &duration) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(zero_capacity.front() == '#');
    CHECK(duration == -7.0f);

    std::vector<char> null_duration(animation_capacity, '#');
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, null_duration.data(), null_duration.size(),
              nullptr) == ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(null_duration.front() == '#');

    std::vector<char> too_small(animation_capacity - 1u, '#');
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, too_small.data(), too_small.size(), &duration) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(duration == -7.0f);
    CHECK(too_small.front() == '#');

    std::vector<char> animation_name(animation_capacity, '#');
    CHECK(arkclaw_spine38_animation_info(
              handle, 0, animation_name.data(), animation_name.size(),
              &duration) == ARKCLAW_SPINE38_OK);
    CHECK(std::memcmp(
              animation_name.data(), animation_name_fixture,
              sizeof(animation_name_fixture)) == 0);
    CHECK(animation_name.back() == '\0');
    CHECK(std::isfinite(duration));
    CHECK(duration == 1.25f);
    CHECK(duration > 0.0f);

    std::vector<char> missing_animation(animation_capacity, '#');
    duration = -9.0f;
    CHECK(arkclaw_spine38_animation_info(
              handle, 1, missing_animation.data(), missing_animation.size(),
              &duration) == ARKCLAW_SPINE38_ANIMATION_NOT_FOUND);
    CHECK(missing_animation.front() == '#');
    CHECK(duration == -9.0f);
    CHECK(arkclaw_spine38_animation_name_size(handle, 1) == 0u);

    CHECK(arkclaw_spine38_skin_count(handle) == 1u);
    const size_t skin_capacity = arkclaw_spine38_skin_name_size(handle, 0);
    CHECK(skin_capacity == sizeof("fixture-skin"));
    CHECK(arkclaw_spine38_skin_info(
              handle, 0, nullptr, skin_capacity) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    std::vector<char> zero_skin_capacity(skin_capacity, '#');
    CHECK(arkclaw_spine38_skin_info(
              handle, 0, zero_skin_capacity.data(), 0) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(zero_skin_capacity.front() == '#');
    std::vector<char> skin_name(skin_capacity, '#');
    CHECK(arkclaw_spine38_skin_info(
              handle, 0, skin_name.data(), skin_name.size() - 1u) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(skin_name.front() == '#');
    CHECK(arkclaw_spine38_skin_info(
              handle, 0, skin_name.data(), skin_name.size()) ==
          ARKCLAW_SPINE38_OK);
    CHECK(std::strcmp(skin_name.data(), "fixture-skin") == 0);
    std::vector<char> missing_skin(skin_capacity, '#');
    CHECK(arkclaw_spine38_skin_info(
              handle, 1, missing_skin.data(), missing_skin.size()) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(missing_skin.front() == '#');

    ArkClawSpine38Bounds bounds{-10.0f, -10.0f, -10.0f, -10.0f};
    CHECK(arkclaw_spine38_setup_bounds(handle, &bounds) ==
          ARKCLAW_SPINE38_OK);
    CHECK(bounds.x == -2.0f);
    CHECK(bounds.y == 3.0f);
    CHECK(bounds.width == 4.0f);
    CHECK(bounds.height == 5.0f);
    CHECK(arkclaw_spine38_setup_bounds(handle, nullptr) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);
    ArkClawSpine38RootTransform root{-10.0f, -10.0f};
    CHECK(arkclaw_spine38_root_transform(handle, &root) ==
          ARKCLAW_SPINE38_OK);
    CHECK(root.x == 0.0f);
    CHECK(root.y == 0.0f);
    CHECK(arkclaw_spine38_root_transform(handle, nullptr) ==
          ARKCLAW_SPINE38_INVALID_ARGUMENT);

    arkclaw_spine38_destroy(handle);
}

}  // namespace

int main() {
    check_fixed_contract_values();
    check_texture_filter_metadata();
    check_atlas_leading_whitespace_contract();
    check_zero_duration_animation_is_not_exposed();
    check_playback_contract_without_drawables();
    check_track_zero_event_contract();
    check_region_draw_view_is_materialized();
    check_mesh_blend_modes_and_draw_order_are_materialized();
    check_clipping_is_applied_inside_the_abi();
    check_malformed_clipped_mesh_index_fails_closed();
    check_unrepresentable_clipped_mesh_fails_closed();
    check_malformed_clipping_polygon_fails_closed();
    check_inactive_bone_slots_are_skipped_and_end_clipping();
    check_unsupported_active_attachment_fails_closed();
    check_fully_clipped_attachment_is_a_valid_empty_draw();
    check_invalid_inputs_do_not_escape_exceptions();
    check_synthetic_catalog_and_buffers();
    return failures == 0 ? 0 : 1;
}
