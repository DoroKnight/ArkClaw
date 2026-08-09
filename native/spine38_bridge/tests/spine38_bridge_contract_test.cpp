#include "sjtuclaw_spine38_bridge.h"

#include <cmath>
#include <cstdint>
#include <cstring>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

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

constexpr char atlas_fixture[] =
    "fixture-page.png\n"
    "size: 1,1\n"
    "format: RGBA8888\n"
    "filter: Nearest,Nearest\n"
    "repeat: none\n";

void check_atlas_leading_whitespace_contract() {
    const auto skeleton = make_synthetic_skeleton();
    const std::vector<std::string> valid_atlases{
        std::string("\n") + atlas_fixture,
        std::string(" \t\r\n\r\n\t \n") + atlas_fixture,
    };

    for (const std::string& atlas : valid_atlases) {
        SjtuclawSpine38Handle* handle = nullptr;
        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas.data(), atlas.size(),
                  &handle) == SJTUCLAW_SPINE38_OK);
        CHECK(handle != nullptr);
        if (handle != nullptr) {
            CHECK(sjtuclaw_spine38_animation_count(handle) == 1u);
            sjtuclaw_spine38_destroy(handle);
        }
    }

    const std::vector<std::string> invalid_atlases{
        " \t\r\n\r\n\t \n",
        "\nfixture-page.png\nsize: 1,1\nformat: RGBA8888\n",
    };
    for (const std::string& atlas : invalid_atlases) {
        SjtuclawSpine38Handle* handle = reinterpret_cast<
            SjtuclawSpine38Handle*>(static_cast<uintptr_t>(1));
        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas.data(), atlas.size(),
                  &handle) == SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED);
        CHECK(handle == nullptr);
    }
}

void check_fixed_contract_values() {
    CHECK(sjtuclaw_spine38_abi_version() == 1u);
    CHECK(SJTUCLAW_SPINE38_OK == 0);
    CHECK(SJTUCLAW_SPINE38_INVALID_ARGUMENT == 1);
    CHECK(SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED == 2);
    CHECK(SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED == 3);
    CHECK(SJTUCLAW_SPINE38_ANIMATION_NOT_FOUND == 4);
    CHECK(SJTUCLAW_SPINE38_RUNTIME_FAILURE == 5);
}

void check_zero_duration_animation_is_not_exposed() {
    const auto skeleton = make_synthetic_skeleton(true);
    SjtuclawSpine38Handle* handle = nullptr;
    CHECK(sjtuclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == SJTUCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(sjtuclaw_spine38_animation_count(handle) == 1u);
    const size_t capacity = sjtuclaw_spine38_animation_name_size(handle, 0);
    CHECK(capacity == sizeof(animation_name_fixture));
    std::vector<char> name(capacity, '#');
    float duration = -1.0f;
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, name.data(), name.size(), &duration) ==
          SJTUCLAW_SPINE38_OK);
    CHECK(std::memcmp(
              name.data(), animation_name_fixture,
              sizeof(animation_name_fixture)) == 0);
    CHECK(duration == 1.25f);
    CHECK(sjtuclaw_spine38_animation_name_size(handle, 1) == 0u);
    sjtuclaw_spine38_destroy(handle);
}

void check_invalid_inputs_do_not_escape_exceptions() {
    SjtuclawSpine38Handle* handle = reinterpret_cast<SjtuclawSpine38Handle*>(
        static_cast<uintptr_t>(1));
    const auto skeleton = make_synthetic_skeleton();
    const uint8_t nonnull_byte = 0;

    try {
        CHECK(sjtuclaw_spine38_create(
                  nullptr, 0, nullptr, 0, &handle) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        const size_t oversized_span =
            static_cast<size_t>(std::numeric_limits<int>::max()) + 1u;
        handle = reinterpret_cast<SjtuclawSpine38Handle*>(
            static_cast<uintptr_t>(1));
        CHECK(sjtuclaw_spine38_create(
                  &nonnull_byte, oversized_span, atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);
        handle = reinterpret_cast<SjtuclawSpine38Handle*>(
            static_cast<uintptr_t>(1));
        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture,
                  oversized_span, &handle) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        CHECK(sjtuclaw_spine38_create(
                  &nonnull_byte, 0, atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);
        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture, 0,
                  &handle) == SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(handle == nullptr);

        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), atlas_fixture,
                  sizeof(atlas_fixture) - 1u, nullptr) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);

        CHECK(sjtuclaw_spine38_create(
                  skeleton.data(), skeleton.size(), "not-an-atlas", 12,
                  &handle) == SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED);
        CHECK(handle == nullptr);

        const uint8_t invalid_skeleton[] = {0};
        CHECK(sjtuclaw_spine38_create(
                  invalid_skeleton, sizeof(invalid_skeleton), atlas_fixture,
                  sizeof(atlas_fixture) - 1u, &handle) ==
              SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED);
        CHECK(handle == nullptr);

        CHECK(sjtuclaw_spine38_animation_count(nullptr) == 0u);
        CHECK(sjtuclaw_spine38_animation_name_size(nullptr, 0) == 0u);
        CHECK(sjtuclaw_spine38_skin_count(nullptr) == 0u);
        CHECK(sjtuclaw_spine38_skin_name_size(nullptr, 0) == 0u);

        char name[8] = {'#', '#', '#', '#', '#', '#', '#', '#'};
        float duration = -1.0f;
        CHECK(sjtuclaw_spine38_animation_info(
                  nullptr, 0, name, sizeof(name), &duration) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(name[0] == '#');
        CHECK(duration == -1.0f);
        CHECK(sjtuclaw_spine38_skin_info(
                  nullptr, 0, name, sizeof(name)) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(name[0] == '#');
        SjtuclawSpine38Bounds bounds{-1.0f, -2.0f, -3.0f, -4.0f};
        CHECK(sjtuclaw_spine38_setup_bounds(nullptr, &bounds) ==
              SJTUCLAW_SPINE38_INVALID_ARGUMENT);
        CHECK(bounds.x == -1.0f);
        CHECK(bounds.y == -2.0f);
        CHECK(bounds.width == -3.0f);
        CHECK(bounds.height == -4.0f);

        sjtuclaw_spine38_destroy(nullptr);
        sjtuclaw_spine38_destroy(nullptr);
    } catch (...) {
        CHECK(false);
    }
}

void check_synthetic_catalog_and_buffers() {
    const auto skeleton = make_synthetic_skeleton();
    SjtuclawSpine38Handle* handle = nullptr;
    CHECK(sjtuclaw_spine38_create(
              skeleton.data(), skeleton.size(), atlas_fixture,
              sizeof(atlas_fixture) - 1u, &handle) == SJTUCLAW_SPINE38_OK);
    CHECK(handle != nullptr);
    if (handle == nullptr) {
        return;
    }

    CHECK(sjtuclaw_spine38_animation_count(handle) == 1u);
    const size_t animation_capacity =
        sjtuclaw_spine38_animation_name_size(handle, 0);
    CHECK(animation_capacity == sizeof(animation_name_fixture));

    float duration = -7.0f;
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, nullptr, animation_capacity, &duration) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(duration == -7.0f);

    std::vector<char> zero_capacity(animation_capacity, '#');
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, zero_capacity.data(), 0, &duration) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(zero_capacity.front() == '#');
    CHECK(duration == -7.0f);

    std::vector<char> null_duration(animation_capacity, '#');
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, null_duration.data(), null_duration.size(),
              nullptr) == SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(null_duration.front() == '#');

    std::vector<char> too_small(animation_capacity - 1u, '#');
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, too_small.data(), too_small.size(), &duration) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(duration == -7.0f);
    CHECK(too_small.front() == '#');

    std::vector<char> animation_name(animation_capacity, '#');
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 0, animation_name.data(), animation_name.size(),
              &duration) == SJTUCLAW_SPINE38_OK);
    CHECK(std::memcmp(
              animation_name.data(), animation_name_fixture,
              sizeof(animation_name_fixture)) == 0);
    CHECK(animation_name.back() == '\0');
    CHECK(std::isfinite(duration));
    CHECK(duration == 1.25f);
    CHECK(duration > 0.0f);

    std::vector<char> missing_animation(animation_capacity, '#');
    duration = -9.0f;
    CHECK(sjtuclaw_spine38_animation_info(
              handle, 1, missing_animation.data(), missing_animation.size(),
              &duration) == SJTUCLAW_SPINE38_ANIMATION_NOT_FOUND);
    CHECK(missing_animation.front() == '#');
    CHECK(duration == -9.0f);
    CHECK(sjtuclaw_spine38_animation_name_size(handle, 1) == 0u);

    CHECK(sjtuclaw_spine38_skin_count(handle) == 1u);
    const size_t skin_capacity = sjtuclaw_spine38_skin_name_size(handle, 0);
    CHECK(skin_capacity == sizeof("fixture-skin"));
    CHECK(sjtuclaw_spine38_skin_info(
              handle, 0, nullptr, skin_capacity) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    std::vector<char> zero_skin_capacity(skin_capacity, '#');
    CHECK(sjtuclaw_spine38_skin_info(
              handle, 0, zero_skin_capacity.data(), 0) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(zero_skin_capacity.front() == '#');
    std::vector<char> skin_name(skin_capacity, '#');
    CHECK(sjtuclaw_spine38_skin_info(
              handle, 0, skin_name.data(), skin_name.size() - 1u) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(skin_name.front() == '#');
    CHECK(sjtuclaw_spine38_skin_info(
              handle, 0, skin_name.data(), skin_name.size()) ==
          SJTUCLAW_SPINE38_OK);
    CHECK(std::strcmp(skin_name.data(), "fixture-skin") == 0);
    std::vector<char> missing_skin(skin_capacity, '#');
    CHECK(sjtuclaw_spine38_skin_info(
              handle, 1, missing_skin.data(), missing_skin.size()) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);
    CHECK(missing_skin.front() == '#');

    SjtuclawSpine38Bounds bounds{-10.0f, -10.0f, -10.0f, -10.0f};
    CHECK(sjtuclaw_spine38_setup_bounds(handle, &bounds) ==
          SJTUCLAW_SPINE38_OK);
    CHECK(bounds.x == -2.0f);
    CHECK(bounds.y == 3.0f);
    CHECK(bounds.width == 4.0f);
    CHECK(bounds.height == 5.0f);
    CHECK(sjtuclaw_spine38_setup_bounds(handle, nullptr) ==
          SJTUCLAW_SPINE38_INVALID_ARGUMENT);

    sjtuclaw_spine38_destroy(handle);
}

}  // namespace

int main() {
    check_fixed_contract_values();
    check_atlas_leading_whitespace_contract();
    check_zero_duration_animation_is_not_exposed();
    check_invalid_inputs_do_not_escape_exceptions();
    check_synthetic_catalog_and_buffers();
    return failures == 0 ? 0 : 1;
}
