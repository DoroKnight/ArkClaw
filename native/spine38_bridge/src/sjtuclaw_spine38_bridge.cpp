#include "sjtuclaw_spine38_bridge.h"

#include <spine/Animation.h>
#include <spine/AnimationState.h>
#include <spine/AnimationStateData.h>
#include <spine/Atlas.h>
#include <spine/AtlasAttachmentLoader.h>
#include <spine/Extension.h>
#include <spine/Skeleton.h>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonData.h>
#include <spine/Skin.h>
#include <spine/TextureLoader.h>

#include <cmath>
#include <cstring>
#include <limits>
#include <memory>
#include <new>
#include <string>

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
        page.texturePath = path;
        page.setRendererObject(&texture_page_token_);
    }

    void unload(void*) override {}

    bool accepted_one_page() const noexcept {
        return accepted_ && load_count_ == 1u && !page_name_.empty() &&
               !texture_path_.empty();
    }

private:
    size_t load_count_ = 0;
    bool accepted_ = false;
    uint8_t texture_page_token_ = 0;
    std::string page_name_;
    std::string texture_path_;
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
    const size_t first_line_end = text.find_first_of("\r\n");
    if (first_line_end == std::string::npos || first_line_end == 0u) {
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

SjtuclawSpine38Code copy_runtime_string(
    const spine::String& source,
    char* destination,
    size_t capacity) noexcept {
    if (!valid_runtime_string(source) || destination == nullptr ||
        capacity <= source.length()) {
        return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
    }
    std::memcpy(destination, source.buffer(), source.length());
    destination[source.length()] = '\0';
    return SJTUCLAW_SPINE38_OK;
}

}  // namespace

struct SjtuclawSpine38Handle {
    std::unique_ptr<CatalogTextureLoader> texture_loader;
    std::unique_ptr<spine::Atlas> atlas;
    std::unique_ptr<spine::AtlasAttachmentLoader> attachment_loader;
    std::unique_ptr<spine::SkeletonData> skeleton_data;
    std::unique_ptr<spine::Skeleton> skeleton;
    std::unique_ptr<spine::AnimationStateData> animation_state_data;
    std::unique_ptr<spine::AnimationState> animation_state;
};

uint32_t sjtuclaw_spine38_abi_version(void) {
    try {
        return 1u;
    } catch (...) {
        return 0u;
    }
}

SjtuclawSpine38Code sjtuclaw_spine38_create(
    const uint8_t* skeleton,
    size_t skeleton_size,
    const char* atlas,
    size_t atlas_size,
    SjtuclawSpine38Handle** out_handle) {
    if (out_handle == nullptr) {
        return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
    }
    *out_handle = nullptr;

    try {
        if (skeleton == nullptr || skeleton_size == 0u || atlas == nullptr ||
            atlas_size == 0u ||
            skeleton_size >
                static_cast<size_t>(std::numeric_limits<int>::max()) ||
            atlas_size > static_cast<size_t>(std::numeric_limits<int>::max())) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        if (!atlas_has_supported_shape(atlas, atlas_size)) {
            return SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }

        auto result = std::make_unique<SjtuclawSpine38Handle>();
        result->texture_loader = std::make_unique<CatalogTextureLoader>();
        try {
            result->atlas = std::make_unique<spine::Atlas>(
                atlas,
                static_cast<int>(atlas_size),
                "",
                result->texture_loader.get(),
                true);
        } catch (const std::bad_alloc&) {
            return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
        } catch (...) {
            return SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }
        if (result->atlas->getPages().size() != 1u ||
            !result->texture_loader->accepted_one_page()) {
            return SJTUCLAW_SPINE38_ATLAS_LOAD_FAILED;
        }

        if (!skeleton_declares_spine38(skeleton, skeleton_size)) {
            return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
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
            return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
        } catch (...) {
            return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }
        result->skeleton_data.reset(parsed);
        if (result->skeleton_data == nullptr || !binary.getError().isEmpty()) {
            return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }

        const spine::String& version = result->skeleton_data->getVersion();
        if (version.buffer() == nullptr || version.length() < 4u ||
            std::memcmp(version.buffer(), "3.8.", 4u) != 0 ||
            result->skeleton_data->getBones().size() == 0u ||
            !valid_bounds(*result->skeleton_data)) {
            return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
        }

        auto& animations = result->skeleton_data->getAnimations();
        for (size_t index = 0u; index < animations.size(); ++index) {
            if (animations[index] == nullptr ||
                !valid_runtime_string(animations[index]->getName()) ||
                !std::isfinite(animations[index]->getDuration()) ||
                animations[index]->getDuration() <= 0.0f) {
                return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
            }
        }
        auto& skins = result->skeleton_data->getSkins();
        for (size_t index = 0u; index < skins.size(); ++index) {
            if (skins[index] == nullptr ||
                !valid_runtime_string(skins[index]->getName())) {
                return SJTUCLAW_SPINE38_SKELETON_LOAD_FAILED;
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

        *out_handle = result.release();
        return SJTUCLAW_SPINE38_OK;
    } catch (...) {
        return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

void sjtuclaw_spine38_destroy(SjtuclawSpine38Handle* handle) {
    try {
        delete handle;
    } catch (...) {
    }
}

size_t sjtuclaw_spine38_animation_count(
    const SjtuclawSpine38Handle* handle) {
    try {
        return handle == nullptr
                   ? 0u
                   : handle->skeleton_data->getAnimations().size();
    } catch (...) {
        return 0u;
    }
}

size_t sjtuclaw_spine38_animation_name_size(
    const SjtuclawSpine38Handle* handle,
    size_t index) {
    try {
        if (handle == nullptr) {
            return 0u;
        }
        auto& animations = handle->skeleton_data->getAnimations();
        if (index >= animations.size() || animations[index] == nullptr ||
            !valid_runtime_string(animations[index]->getName())) {
            return 0u;
        }
        return animations[index]->getName().length() + 1u;
    } catch (...) {
        return 0u;
    }
}

SjtuclawSpine38Code sjtuclaw_spine38_animation_info(
    const SjtuclawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity,
    float* duration_seconds) {
    try {
        if (handle == nullptr || name_utf8 == nullptr ||
            duration_seconds == nullptr) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        auto& animations = handle->skeleton_data->getAnimations();
        if (index >= animations.size() || animations[index] == nullptr) {
            return SJTUCLAW_SPINE38_ANIMATION_NOT_FOUND;
        }
        spine::Animation& animation = *animations[index];
        if (name_capacity <= animation.getName().length()) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        if (!std::isfinite(animation.getDuration()) ||
            animation.getDuration() <= 0.0f) {
            return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
        }
        const SjtuclawSpine38Code copied = copy_runtime_string(
            animation.getName(), name_utf8, name_capacity);
        if (copied != SJTUCLAW_SPINE38_OK) {
            return copied;
        }
        *duration_seconds = animation.getDuration();
        return SJTUCLAW_SPINE38_OK;
    } catch (...) {
        return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

size_t sjtuclaw_spine38_skin_count(const SjtuclawSpine38Handle* handle) {
    try {
        return handle == nullptr ? 0u
                                 : handle->skeleton_data->getSkins().size();
    } catch (...) {
        return 0u;
    }
}

size_t sjtuclaw_spine38_skin_name_size(
    const SjtuclawSpine38Handle* handle,
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

SjtuclawSpine38Code sjtuclaw_spine38_skin_info(
    const SjtuclawSpine38Handle* handle,
    size_t index,
    char* name_utf8,
    size_t name_capacity) {
    try {
        if (handle == nullptr || name_utf8 == nullptr) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        auto& skins = handle->skeleton_data->getSkins();
        if (index >= skins.size() || skins[index] == nullptr) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        return copy_runtime_string(
            skins[index]->getName(), name_utf8, name_capacity);
    } catch (...) {
        return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
    }
}

SjtuclawSpine38Code sjtuclaw_spine38_setup_bounds(
    const SjtuclawSpine38Handle* handle,
    SjtuclawSpine38Bounds* out_bounds) {
    try {
        if (handle == nullptr || out_bounds == nullptr) {
            return SJTUCLAW_SPINE38_INVALID_ARGUMENT;
        }
        spine::SkeletonData& data = *handle->skeleton_data;
        if (!valid_bounds(data)) {
            return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
        }
        const SjtuclawSpine38Bounds bounds{
            data.getX(), data.getY(), data.getWidth(), data.getHeight()};
        *out_bounds = bounds;
        return SJTUCLAW_SPINE38_OK;
    } catch (...) {
        return SJTUCLAW_SPINE38_RUNTIME_FAILURE;
    }
}
