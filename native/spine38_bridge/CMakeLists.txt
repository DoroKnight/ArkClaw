cmake_minimum_required(VERSION 3.25)
project(sjtuclaw_spine38_bridge LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(SPINE_RUNTIMES_SOURCE_DIR "" CACHE PATH "Exact pinned spine-runtimes checkout")

if(NOT EXISTS "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/include/spine/spine.h")
  message(FATAL_ERROR "SPINE_RUNTIMES_SOURCE_DIR is not a spine-runtimes checkout")
endif()
if(NOT EXISTS "${SPINE_RUNTIMES_SOURCE_DIR}/LICENSE")
  message(FATAL_ERROR "SPINE_RUNTIMES_SOURCE_DIR is missing its license")
endif()

file(GLOB SPINE38_SOURCES CONFIGURE_DEPENDS
  "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/src/spine/*.cpp")
add_library(spine38_runtime STATIC ${SPINE38_SOURCES})
target_include_directories(spine38_runtime PUBLIC
  "${SPINE_RUNTIMES_SOURCE_DIR}/spine-cpp/spine-cpp/include")
set_target_properties(spine38_runtime PROPERTIES POSITION_INDEPENDENT_CODE ON)

add_library(sjtuclaw_spine38_bridge SHARED
  src/sjtuclaw_spine38_bridge.cpp)
target_link_libraries(sjtuclaw_spine38_bridge PRIVATE spine38_runtime)
target_include_directories(sjtuclaw_spine38_bridge PUBLIC include)
add_custom_command(
  TARGET sjtuclaw_spine38_bridge
  POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${SPINE_RUNTIMES_SOURCE_DIR}/LICENSE"
    "$<TARGET_FILE_DIR:sjtuclaw_spine38_bridge>/LICENSE"
  VERBATIM)

enable_testing()
