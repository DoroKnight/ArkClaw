#include "arkclaw_spine38_bridge.h"

#include <spine/Animation.h>
#include <spine/AnimationState.h>
#include <spine/AnimationStateData.h>
#include <spine/Attachment.h>
#include <spine/Atlas.h>
#include <spine/AtlasAttachmentLoader.h>
#include <spine/Bone.h>
#include <spine/ClippingAttachment.h>
#include <spine/Extension.h>
#include <spine/MeshAttachment.h>
#include <spine/RegionAttachment.h>
#include <spine/Skeleton.h>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonClipping.h>
#include <spine/SkeletonData.h>
#include <spine/Skin.h>
#include <spine/Slot.h>
#include <spine/SlotData.h>
#include <spine/TextureLoader.h>

#include <cctype>
#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <string>
#include <vector>

namespace spine {

SpineExtension* getDefaultExtension() {
    return new DefaultSpineExtension();
}

}  // namespace spine

namespace {

class CatalogTextureLoader final : public spine::TextureLoader {
public:
    void load(spine::AtlasPage& page, const spine::String& path) override {
        ++load_count_;
        if (load_count_ != 1u || path.isEmpty() || page.name.isEmpty() ||
            page.width <= 0 || page.height <= 0) {
            accepted_ = false;
            return;
        }

        accepted_ = true;
        page_name_.assign(page.name.buffer(), page.name.length());
        texture_path_.assign(path.buffer(), path.length());
        min_filter_ = map_filter(page.minFilter);
        mag_filter_ = map_filter(page.magFilter);
        page.texturePath = path;
        page.setRendererObject(&texture_page_token_);
    }

    void unload(void*) override {}

    bool accepted_one_page() const noexcept {
        return accepted_ && load_count_ == 1u && !page_name_.empty() &&
               !texture_path_.empty();
    }

    uint32_t min_filter() const noexcept { return min_filter_; }
    uint32_t mag_filter() const noexcept { return mag_filter_; }

private:
    static uint32_t map_filter(spine::TextureFilter value) noexcept {
        switch (value) {
        case spine::TextureFilter_Nearest:
            return ARKCLAW_SPINE38_FILTER_NEAREST;
        case spine::TextureFilter_Linear:
            return ARKCLAW_SPINE38_FILTER_LINEAR;
        default:
            return ARKCLAW_SPINE38_FILTER_UNKNOWN;
        }
    }

    size_t load_count_ = 0;
    bool accepted_ = false;
    uint8_t texture_page_token_ = 0;
    std::string page_name_;
    std::string texture_path_;
    uint32_t min_filter_ = ARKCLAW_SPINE38_FILTER_UNKNOWN;
    uint32_t mag_filter_ = ARKCLAW_SPINE38_FILTER_UNKNOWN;
};

bool atlas_has_supported_shape(const char* atlas, size_t atlas_size) {
    if (atlas == nullptr || atlas_size == 0u ||
        atlas_size > static_cast<size_t>(std::numeric_limits<int>::max())) {
        return false;
    }
    if (std::memchr(atlas, '\0', atlas_size) != nullptr) {
        return false;
    }

    const std::string text(atlas, atlas_size);
    size_t first_content = 0u;
    while (first_content < text.size() &&
           std::isspace(static_cast<unsigned char>(text[first_content]))) {
        ++first_content;
    }
    if (first_content == text.size()) {
        return false;
    }

    const size_t first_line_end = text.find_first_of("\r\n", first_content);
    if (first_line_end == std::string::npos ||
        first_line_end == first_content) {
        return false;
    }
    return text.find("size:", first_line_end) != std::string::npos &&
           text.find("format:", first_line_end) != std::string::npos &&
           text.find("filter:", first_line_end) != std::string::npos &&
           text.find("repeat:", first_line_end) != std::string::npos;
}

bool read_varint(
    const uint8_t*& cursor,
    const uint8_t* end,
    uint32_t& value) noexcept {
    value = 0u;
    for (unsigned shift = 0u; shift <= 28u; shift += 7u) {
        if (cursor == end) {
            return false;
        }
        const uint8_t byte = *cursor++;
        value |= static_cast<uint32_t>(byte & 0x7fu) << shift;
        if ((byte & 0x80u) == 0u) {
            return true;
        }
    }
    return false;
}

bool read_binary_string_view(
    const uint8_t*& cursor,
    const uint8_t* end,
    const uint8_t*& string_data,
    size_t& string_size) noexcept {
    uint32_t encoded_length = 0u;
    if (!read_varint(cursor, end, encoded_length)) {
        return false;
    }
    if (encoded_length == 0u) {
        string_data = nullptr;
        string_size = 0u;
        return true;
    }

    string_size = static_cast<size_t>(encoded_length - 1u);
    if (string_size > static_cast<size_t>(end - cursor)) {
        return false;
    }
    string_data = cursor;
    cursor += string_size;
    return true;
}

bool skeleton_declares_spine38(
    const uint8_t* skeleton,
    size_t skeleton_size) noexcept {
    if (skeleton == nullptr || skeleton_size == 0u ||
        skeleton_size > static_cast<size_t>(std::numeric_limits<int>::max())) {
        return false;
    }

    const uint8_t* cursor = skeleton;
    const uint8_t* const end = skeleton + skeleton_size;
    const uint8_t* value = nullptr;
    size_t value_size = 0u;
    if (!read_binary_string_view(cursor, end, value, value_size)) {
        return false;
    }
    if (!read_binary_string_view(cursor, end, value, value_size)) {
        return false;
    }
    return value != nullptr && value_size >= 4u &&
           std::memcmp(value, "3.8.", 4u) == 0;
}

bool valid_runtime_string(const spine::String& value) noexcept {
    return !value.isEmpty() && value.buffer() != nullptr &&
           value.length() < std::numeric_limits<size_t>::max();
}

bool valid_bounds(spine::SkeletonData& data) noexcept {
    return std::isfinite(data.getX()) && std::isfinite(data.getY()) &&
           std::isfinite(data.getWidth()) && std::isfinite(data.getHeight()) &&
           data.getWidth() > 0.0f && data.getHeight() > 0.0f;
}

ArkClawSpine38Code copy_runtime_string(
    const spine::String& source,
    char* destination,
    size_t capacity) noexcept {
    if (!valid_runtime_string(source) || destination == nullptr ||
        capacity <= source.length()) {
        return ARKCLAW_SPINE38_INVALID_ARGUMENT;
    }
    std::memcpy(destination, source.buffer(), source.length());
    destination[source.length()] = '\0';
    return ARKCLAW_SPINE38_OK;
}

uint8_t color_byte(float value) noexcept {
    if (!std::isfinite(value)) {
        return 0u;
    }
    if (value <= 0.0f) {
        return 0u;
    }
    if (value >= 1.0f) {
        return 255u;
    }
    return static_cast<uint8_t>(value * 255.0f);
}

bool map_blend_mode(spine::BlendMode mode, uint32_t& output) noexcept {
    switch (mode) {
    case spine::BlendMode_Normal:
        output = ARKCLAW_SPINE38_BLEND_NORMAL;
        return true;
    case spine::BlendMode_Additive:
        output = ARKCLAW_SPINE38_BLEND_ADDITIVE;
        return true;
    case spine::BlendMode_Multiply:
        output = ARKCLAW_SPINE38_BLEND_MULTIPLY;
        return true;
    case spine::BlendMode_Screen:
        output = ARKCLAW_SPINE38_BLEND_SCREEN;
        return true;
    default:
        return false;
    }
}

}  // namespace

struct OwnedDrawCommand {
    std::vector<ArkClawSpine38Vertex> vertices;
    std::vector<uint32_t> indices;
    uint32_t texture_page = 0u;
    uint32_t blend_mode = ARKCLAW_SPINE38_BLEND_NORMAL;
    int32_t draw_order = 0;

    ArkClawSpine38DrawView view() const noexcept {
        return ArkClawSpine38DrawView{
            vertices.data(), vertices.size(), indices.data(), indices.size(),
            texture_page, blend_mode, draw_order};
    }
};

struct OwnedPlaybackEvent {
    uint32_t event_type = ARKCLAW_SPINE38_EVENT_COMPLETE;
    uint32_t track = 0u;
    uint64_t loop_ordinal = 0u;
    std::string animation_name;

    ArkClawSpine38EventView view() const noexcept {
        return ArkClawSpine38EventView{
            event_type,
            track,
            loop_ordinal,
            animation_name.data(),
            animation_name.size()};
    }
};

struct ArkClawSpine38Handle {
    std::unique_ptr<CatalogTextureLoader> texture_loader;
    std::unique_ptr<spine::Atlas> atlas;
    std::unique_ptr<spine::AtlasAttachmentLoader> attachment_loader;
    std::unique_ptr<spine::SkeletonData> skeleton_data;
    std::vector<spine::Animation*> animation_catalog;
    std::unique_ptr<spine::Skeleton> skeleton;
    std::unique_ptr<spine::AnimationStateData> animation_state_data;
    std::unique_ptr<spine::AnimationState> animation_state;
    std::vector<OwnedDrawCommand> draw_commands;
    std::vector<OwnedPlaybackEvent> playback_events;
    uint64_t track_zero_loop_ordinal = 0u;
};

namespace {

void capture_animation_event(
    spine::AnimationState* state,
    spine::EventType type,
    spine::TrackEntry* entry,
    spine::Event*) {
    if (state == nullptr || type != spine::EventType_Complete ||
        entry == nullptr || entry->getTrackIndex() != 0) {
        return;
    }
    auto* handle = static_cast<ArkClawSpine38Handle*>(
        state->getRendererObject());
    spine::Animation* animation = entry->getAnimation();
    if (handle == nullptr || animation == nullptr ||
        state->getCurrent(0u) != entry ||
        !valid_runtime_string(animation->getName()) ||
        !std::isfinite(animation->getDuration()) ||
        animation->getDuration() <= 0.0f) {
        return;
    }
    OwnedPlaybackEvent event;
    event.track = 0u;
    event.animation_name.assign(
        animation->getName().buffer(), animation->getName().length());
    if (entry->getLoop()) {
        ++handle->track_zero_loop_ordinal;
        event.event_type = ARKCLAW_SPINE38_EVENT_LOOP_BOUNDARY;
        event.loop_ordinal = handle->track_zero_loop_ordinal;
    }
    handle->playback_events.push_back(std::move(event));
}

}  // namespace

uint32_t arkclaw_spine38_abi_version(void) {
    try {
        return 1u;
    } catch (...) {
        return 0u;
    }
}

ArkClawSpine38Code arkclaw_spine38_root_transform(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38RootTransform* out_transform) {
    try {
        if (handle == nullptr || out_transform == nullptr ||
            handle->skeleton == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        spine::Bone* root = handle->skeleton->getRootBone();
        if (root == nullptr || !std::isfinite(root->getWorldX()) ||
            !std::isfinite(root->getWorldY())) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        }
        const ArkClawSpine38RootTransform next{
            root->getWorldX(),
            root->getWorldY(),
        };
        *out_transform = next;
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_create(
    const uint8_t* skeleton,
    size_t skeleton_size,
    const char* atlas,
    size_t atlas_size,
    ArkClawSpine38Handle** out_handle) {
    if (out_handle == nullptr) {
        return ARKCLAW_SPINE38_INVALID_ARGUMENT;
    }
    *out_handle = nullptr;

    try {
        if (skeleton == nullptr || skeleton_size == 0u || atlas == nullptr ||
            atlas_size == 0u ||
            skeleton_size >
                static_cast<size_t>(std::numeric_limits<int>::max()) ||
            atlas_size > static_cast<size_t>(std::numeric_limits<int>::max())) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        if (!atlas_has_supported_shape(atlas, atlas_size)) {
            return ARKCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }

        auto result = std::make_unique<ArkClawSpine38Handle>();
        result->texture_loader = std::make_unique<CatalogTextureLoader>();
        try {
            result->atlas = std::make_unique<spine::Atlas>(
                atlas,
                static_cast<int>(atlas_size),
                "",
                result->texture_loader.get(),
                true);
        } catch (const std::bad_alloc&) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        } catch (...) {
            return ARKCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }
        if (result->atlas->getPages().size() != 1u ||
            !result->texture_loader->accepted_one_page()) {
            return ARKCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }

        if (!skeleton_declares_spine38(skeleton, skeleton_size)) {
            return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }

        result->attachment_loader =
            std::make_unique<spine::AtlasAttachmentLoader>(result->atlas.get());
        spine::SkeletonBinary binary(result->attachment_loader.get(), false);
        spine::SkeletonData* parsed = nullptr;
        try {
            parsed = binary.readSkeletonData(
                skeleton,
                static_cast<int>(skeleton_size));
        } catch (const std::bad_alloc&) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        } catch (...) {
            return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }
        result->skeleton_data.reset(parsed);
        if (result->skeleton_data == nullptr || !binary.getError().isEmpty()) {
            return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }

        const spine::String& version = result->skeleton_data->getVersion();
        if (version.buffer() == nullptr || version.length() < 4u ||
            std::memcmp(version.buffer(), "3.8.", 4u) != 0 ||
            result->skeleton_data->getBones().size() == 0u ||
            !valid_bounds(*result->skeleton_data)) {
            return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }

        auto& animations = result->skeleton_data->getAnimations();
        for (size_t index = 0u; index < animations.size(); ++index) {
            if (animations[index] == nullptr ||
                !valid_runtime_string(animations[index]->getName()) ||
                !std::isfinite(animations[index]->getDuration()) ||
                animations[index]->getDuration() < 0.0f) {
                return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
            }
            if (animations[index]->getDuration() > 0.0f) {
                result->animation_catalog.push_back(animations[index]);
            }
        }
        auto& skins = result->skeleton_data->getSkins();
        for (size_t index = 0u; index < skins.size(); ++index) {
            if (skins[index] == nullptr ||
                !valid_runtime_string(skins[index]->getName())) {
                return ARKCLAW_SPINE38_SKELETON_LOAD_FAILED;
            }
        }

        result->skeleton =
            std::make_unique<spine::Skeleton>(result->skeleton_data.get());
        result->skeleton->updateWorldTransform();
        result->animation_state_data =
            std::make_unique<spine::AnimationStateData>(
                result->skeleton_data.get());
        result->animation_state = std::make_unique<spine::AnimationState>(
            result->animation_state_data.get());
        result->animation_state->setRendererObject(result.get());
        result->animation_state->setListener(capture_animation_event);

        *out_handle = result.release();
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

void arkclaw_spine38_destroy(ArkClawSpine38Handle* handle) {
    try {
        delete handle;
    } catch (...) {
    }
}

size_t arkclaw_spine38_animation_count(
    const ArkClawSpine38Handle* handle) {
    try {
        return handle == nullptr
                   ? 0u
                   : handle->animation_catalog.size();
    } catch (...) {
        return 0u;
    }
}

size_t arkclaw_spine38_animation_name_size(
    const ArkClawSpine38Handle* handle,
    size_t index) {
    try {
        if (handle == nullptr) {
            return 0u;
        }
        const auto& animations = handle->animation_catalog;
        if (index >= animations.size() || animations[index] == nullptr ||
            !valid_runtime_string(animations[index]->getName())) {
            return 0u;
        }
        return animations[index]->getName().length() + 1u;
    } catch (...) {
        return 0u;
    }
}

ArkClawSpine38Code arkclaw_spine38_animation_info(
    const ArkClawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity,
    float* duration_seconds) {
    try {
        if (handle == nullptr || name_utf8 == nullptr ||
            duration_seconds == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        const auto& animations = handle->animation_catalog;
        if (index >= animations.size() || animations[index] == nullptr) {
            return ARKCLAW_SPINE38_ANIMATION_NOT_FOUND;
        }
        spine::Animation& animation = *animations[index];
        if (name_capacity <= animation.getName().length()) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        if (!std::isfinite(animation.getDuration()) ||
            animation.getDuration() <= 0.0f) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        }
        const ArkClawSpine38Code copied = copy_runtime_string(
            animation.getName(), name_utf8, name_capacity);
        if (copied != ARKCLAW_SPINE38_OK) {
            return copied;
        }
        *duration_seconds = animation.getDuration();
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

size_t arkclaw_spine38_skin_count(const ArkClawSpine38Handle* handle) {
    try {
        return handle == nullptr ? 0u
                                 : handle->skeleton_data->getSkins().size();
    } catch (...) {
        return 0u;
    }
}

size_t arkclaw_spine38_skin_name_size(
    const ArkClawSpine38Handle* handle,
    size_t index) {
    try {
        if (handle == nullptr) {
            return 0u;
        }
        auto& skins = handle->skeleton_data->getSkins();
        if (index >= skins.size() || skins[index] == nullptr ||
            !valid_runtime_string(skins[index]->getName())) {
            return 0u;
        }
        return skins[index]->getName().length() + 1u;
    } catch (...) {
        return 0u;
    }
}

ArkClawSpine38Code arkclaw_spine38_skin_info(
    const ArkClawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity) {
    try {
        if (handle == nullptr || name_utf8 == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        auto& skins = handle->skeleton_data->getSkins();
        if (index >= skins.size() || skins[index] == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        return copy_runtime_string(
            skins[index]->getName(), name_utf8, name_capacity);
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_setup_bounds(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38Bounds* out_bounds) {
    try {
        if (handle == nullptr || out_bounds == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        spine::SkeletonData& data = *handle->skeleton_data;
        if (!valid_bounds(data)) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        }
        const ArkClawSpine38Bounds bounds{
            data.getX(), data.getY(), data.getWidth(), data.getHeight()};
        *out_bounds = bounds;
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_set_animation(
    ArkClawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop) {
    try {
        constexpr uint32_t max_track = 255u;
        if (handle == nullptr || name_utf8 == nullptr || name_size == 0u ||
            name_size > static_cast<size_t>(std::numeric_limits<int>::max()) ||
            track > max_track || loop > 1u ||
            std::memchr(name_utf8, '\0', name_size) != nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }

        spine::Animation* selected = nullptr;
        for (spine::Animation* animation : handle->animation_catalog) {
            if (animation != nullptr && animation->getName().length() == name_size &&
                std::memcmp(
                    animation->getName().buffer(), name_utf8, name_size) == 0) {
                selected = animation;
                break;
            }
        }
        if (selected == nullptr) {
            return ARKCLAW_SPINE38_ANIMATION_NOT_FOUND;
        }

        // Every installation starts from one canonical pose.  This keeps
        // bootstrap sampling independent of role order and prevents a prior
        // animation's attachments or mixed pose from leaking into the next.
        handle->animation_state->clearTracks();
        handle->skeleton->setToSetupPose();
        if (handle->animation_state->setAnimation(
                static_cast<size_t>(track), selected, loop != 0u) == nullptr) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        }
        handle->playback_events.clear();
        if (track == 0u) {
            handle->track_zero_loop_ordinal = 0u;
        }
        handle->draw_commands.clear();
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_mix_animation(
    ArkClawSpine38Handle* handle,
    uint32_t track,
    const char* name_utf8,
    size_t name_size,
    uint8_t loop,
    float mix_seconds) {
    try {
        constexpr uint32_t max_track = 255u;
        if (handle == nullptr || name_utf8 == nullptr || name_size == 0u ||
            name_size > static_cast<size_t>(std::numeric_limits<int>::max()) ||
            track > max_track || loop > 1u || !std::isfinite(mix_seconds) ||
            mix_seconds < 0.0f ||
            std::memchr(name_utf8, '\0', name_size) != nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }

        spine::Animation* selected = nullptr;
        for (spine::Animation* animation : handle->animation_catalog) {
            if (animation != nullptr && animation->getName().length() == name_size &&
                std::memcmp(
                    animation->getName().buffer(), name_utf8, name_size) == 0) {
                selected = animation;
                break;
            }
        }
        if (selected == nullptr) {
            return ARKCLAW_SPINE38_ANIMATION_NOT_FOUND;
        }

        spine::TrackEntry* entry = handle->animation_state->setAnimation(
            static_cast<size_t>(track), selected, loop != 0u);
        if (entry == nullptr) {
            return ARKCLAW_SPINE38_RUNTIME_FAILURE;
        }
        entry->setMixDuration(mix_seconds);
        handle->playback_events.clear();
        if (track == 0u) {
            handle->track_zero_loop_ordinal = 0u;
        }
        // The Qt composition can switch BODY/OVERFLOW ownership in the same
        // GUI tick as this call. Materialize time-zero immediately so that
        // the new owner never observes an intentionally empty draw list.
        return arkclaw_spine38_update(handle, 0.0f);
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_update(
    ArkClawSpine38Handle* handle,
    float delta_seconds) {
    try {
        if (handle == nullptr || !std::isfinite(delta_seconds) ||
            delta_seconds < 0.0f) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        handle->draw_commands.clear();
        handle->playback_events.clear();
        handle->animation_state->update(delta_seconds);
        handle->animation_state->apply(*handle->skeleton);
        handle->skeleton->updateWorldTransform();

        std::vector<OwnedDrawCommand> next_commands;
        auto& draw_order = handle->skeleton->getDrawOrder();
        next_commands.reserve(draw_order.size());
        spine::SkeletonClipping clipper;
        for (size_t order = 0u; order < draw_order.size(); ++order) {
            spine::Slot* slot = draw_order[order];
            if (slot == nullptr) {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }
            if (!slot->getBone().isActive()) {
                clipper.clipEnd(*slot);
                continue;
            }
            spine::Attachment* attachment = slot->getAttachment();
            if (attachment == nullptr) {
                clipper.clipEnd(*slot);
                continue;
            }
            if (attachment->getRTTI().isExactly(
                    spine::ClippingAttachment::rtti)) {
                auto* clipping_attachment =
                    static_cast<spine::ClippingAttachment*>(attachment);
                const int world_vertex_values =
                    clipping_attachment->getWorldVerticesLength();
                constexpr size_t max_clipping_world_vertex_values =
                    (static_cast<size_t>(
                         std::numeric_limits<unsigned short>::max()) +
                     1u) *
                    2u;
                if (world_vertex_values < 6 ||
                    (world_vertex_values & 1) != 0 ||
                    static_cast<size_t>(world_vertex_values) >
                        max_clipping_world_vertex_values) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
                clipper.clipStart(
                    *slot, clipping_attachment);
                continue;
            }
            std::vector<float> world_vertices;
            spine::Vector<float>* uvs = nullptr;
            std::vector<unsigned short> source_indices;
            spine::Color* attachment_color = nullptr;
            void* renderer_object = nullptr;
            if (attachment->getRTTI().isExactly(
                    spine::RegionAttachment::rtti)) {
                auto* region = static_cast<spine::RegionAttachment*>(attachment);
                world_vertices.resize(8u);
                region->computeWorldVertices(
                    slot->getBone(), world_vertices.data(), 0u, 2u);
                uvs = &region->getUVs();
                source_indices = {0u, 1u, 2u, 2u, 3u, 0u};
                attachment_color = &region->getColor();
                renderer_object = region->getRendererObject();
            } else if (attachment->getRTTI().isExactly(
                           spine::MeshAttachment::rtti)) {
                auto* mesh = static_cast<spine::MeshAttachment*>(attachment);
                const int world_vertices_length =
                    mesh->getWorldVerticesLength();
                if (world_vertices_length <= 0 ||
                    (world_vertices_length & 1) != 0) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
                world_vertices.resize(
                    static_cast<size_t>(world_vertices_length));
                mesh->computeWorldVertices(
                    *slot, 0, world_vertices_length, world_vertices.data(),
                    0u, 2u);
                uvs = &mesh->getUVs();
                auto& mesh_triangles = mesh->getTriangles();
                source_indices.reserve(mesh_triangles.size());
                for (size_t index = 0u; index < mesh_triangles.size(); ++index) {
                    source_indices.push_back(mesh_triangles[index]);
                }
                attachment_color = &mesh->getColor();
                renderer_object = mesh->getRendererObject();
            } else {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }

            auto* atlas_region = static_cast<spine::AtlasRegion*>(
                renderer_object);
            if (atlas_region == nullptr || atlas_region->page == nullptr ||
                handle->atlas->getPages().size() != 1u ||
                atlas_region->page != handle->atlas->getPages()[0]) {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }
            if (uvs == nullptr || uvs->size() != world_vertices.size() ||
                world_vertices.empty() || source_indices.empty() ||
                (source_indices.size() % 3u) != 0u ||
                order > static_cast<size_t>(
                            std::numeric_limits<int32_t>::max())) {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }
            const size_t source_vertex_count = world_vertices.size() / 2u;
            for (unsigned short source_index : source_indices) {
                if (source_index >= source_vertex_count) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
            }

            const float* output_vertices = world_vertices.data();
            const float* output_uvs = uvs->buffer();
            const unsigned short* output_indices = source_indices.data();
            size_t output_vertex_values = world_vertices.size();
            size_t output_index_count = source_indices.size();
            if (clipper.isClipping()) {
                clipper.clipTriangles(
                    world_vertices.data(), source_indices.data(),
                    source_indices.size(), uvs->buffer(), 2u);
                output_vertices = clipper.getClippedVertices().buffer();
                output_uvs = clipper.getClippedUVs().buffer();
                output_indices = clipper.getClippedTriangles().buffer();
                output_vertex_values =
                    clipper.getClippedVertices().size();
                output_index_count = clipper.getClippedTriangles().size();
                constexpr size_t max_clipped_vertex_count =
                    static_cast<size_t>(
                        std::numeric_limits<unsigned short>::max()) +
                    1u;
                if (clipper.getClippedUVs().size() != output_vertex_values ||
                    (output_vertex_values % 2u) != 0u ||
                    output_vertex_values / 2u > max_clipped_vertex_count) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
                if (output_vertex_values == 0u && output_index_count == 0u) {
                    clipper.clipEnd(*slot);
                    continue;
                }
            }
            if (output_vertices == nullptr || output_uvs == nullptr ||
                output_indices == nullptr || output_vertex_values == 0u ||
                (output_vertex_values % 2u) != 0u ||
                output_index_count == 0u || (output_index_count % 3u) != 0u) {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }

            const spine::Color& skeleton_color = handle->skeleton->getColor();
            const spine::Color& slot_color = slot->getColor();
            const uint8_t r = color_byte(
                skeleton_color.r * slot_color.r * attachment_color->r);
            const uint8_t g = color_byte(
                skeleton_color.g * slot_color.g * attachment_color->g);
            const uint8_t b = color_byte(
                skeleton_color.b * slot_color.b * attachment_color->b);
            const uint8_t a = color_byte(
                skeleton_color.a * slot_color.a * attachment_color->a);

            OwnedDrawCommand command;
            if (!map_blend_mode(
                    slot->getData().getBlendMode(), command.blend_mode)) {
                return ARKCLAW_SPINE38_RUNTIME_FAILURE;
            }
            command.draw_order = static_cast<int32_t>(order);
            const size_t vertex_count = output_vertex_values / 2u;
            command.vertices.reserve(vertex_count);
            for (size_t vertex = 0u; vertex < vertex_count; ++vertex) {
                const size_t offset = vertex * 2u;
                if (!std::isfinite(output_vertices[offset]) ||
                    !std::isfinite(output_vertices[offset + 1u]) ||
                    !std::isfinite(output_uvs[offset]) ||
                    !std::isfinite(output_uvs[offset + 1u])) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
                command.vertices.push_back(ArkClawSpine38Vertex{
                    output_vertices[offset], output_vertices[offset + 1u],
                    output_uvs[offset], output_uvs[offset + 1u], r, g, b, a});
            }
            command.indices.reserve(output_index_count);
            for (size_t index = 0u; index < output_index_count; ++index) {
                if (output_indices[index] >= vertex_count) {
                    return ARKCLAW_SPINE38_RUNTIME_FAILURE;
                }
                command.indices.push_back(
                    static_cast<uint32_t>(output_indices[index]));
            }
            next_commands.push_back(std::move(command));
            clipper.clipEnd(*slot);
        }
        clipper.clipEnd();
        handle->draw_commands = std::move(next_commands);
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_clear_track(
    ArkClawSpine38Handle* handle,
    uint32_t track) {
    try {
        constexpr uint32_t max_track = 255u;
        if (handle == nullptr || track > max_track) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        handle->animation_state->clearTrack(static_cast<size_t>(track));
        handle->playback_events.clear();
        if (track == 0u) {
            handle->track_zero_loop_ordinal = 0u;
        }
        handle->draw_commands.clear();
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

size_t arkclaw_spine38_event_count(
    const ArkClawSpine38Handle* handle) {
    try {
        return handle == nullptr ? 0u : handle->playback_events.size();
    } catch (...) {
        return 0u;
    }
}

ArkClawSpine38Code arkclaw_spine38_event_view(
    const ArkClawSpine38Handle* handle,
    size_t index,
    ArkClawSpine38EventView* out_view,
    size_t view_capacity) {
    try {
        if (handle == nullptr || out_view == nullptr ||
            view_capacity < sizeof(ArkClawSpine38EventView) ||
            index >= handle->playback_events.size()) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        const ArkClawSpine38EventView view =
            handle->playback_events[index].view();
        *out_view = view;
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

ArkClawSpine38Code arkclaw_spine38_texture_page_view(
    const ArkClawSpine38Handle* handle,
    ArkClawSpine38TexturePageView* out_view,
    size_t view_capacity) {
    try {
        if (handle == nullptr || out_view == nullptr ||
            view_capacity < sizeof(ArkClawSpine38TexturePageView) ||
            handle->texture_loader == nullptr) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        const ArkClawSpine38TexturePageView candidate{
            handle->texture_loader->min_filter(),
            handle->texture_loader->mag_filter()};
        *out_view = candidate;
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

size_t arkclaw_spine38_draw_count(
    const ArkClawSpine38Handle* handle) {
    try {
        return handle == nullptr ? 0u : handle->draw_commands.size();
    } catch (...) {
        return 0u;
    }
}

ArkClawSpine38Code arkclaw_spine38_draw_view(
    const ArkClawSpine38Handle* handle,
    size_t index,
    ArkClawSpine38DrawView* out_view,
    size_t view_capacity) {
    try {
        if (handle == nullptr || out_view == nullptr ||
            view_capacity < sizeof(ArkClawSpine38DrawView) ||
            index >= handle->draw_commands.size()) {
            return ARKCLAW_SPINE38_INVALID_ARGUMENT;
        }
        *out_view = handle->draw_commands[index].view();
        return ARKCLAW_SPINE38_OK;
    } catch (...) {
        return ARKCLAW_SPINE38_RUNTIME_FAILURE;
    }
}
