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

add_library(sjtuclaw_spine38_bridge_library SHARED
  src/sjtuclaw_spine38_bridge.cpp)
set_target_properties(sjtuclaw_spine38_bridge_library PROPERTIES
  OUTPUT_NAME sjtuclaw_spine38_bridge)
target_compile_definitions(sjtuclaw_spine38_bridge_library PRIVATE
  SJTUCLAW_SPINE38_BRIDGE_BUILD)
target_link_libraries(sjtuclaw_spine38_bridge_library PRIVATE spine38_runtime)
target_include_directories(sjtuclaw_spine38_bridge_library PUBLIC include)
add_custom_command(
  TARGET sjtuclaw_spine38_bridge_library
  POST_BUILD
  COMMAND "${CMAKE_COMMAND}" -E copy_if_different
    "${SPINE_RUNTIMES_SOURCE_DIR}/LICENSE"
    "$<TARGET_FILE_DIR:sjtuclaw_spine38_bridge_library>/LICENSE"
  VERBATIM)

enable_testing()

add_executable(spine38_bridge_contract_test
  tests/spine38_bridge_contract_test.cpp)
target_link_libraries(spine38_bridge_contract_test PRIVATE
  sjtuclaw_spine38_bridge_library)
add_test(NAME spine38_bridge_contract COMMAND spine38_bridge_contract_test)

# The reviewed build wrapper intentionally builds this named target. Keep it
# as the complete native gate so the DLL and its contract executable are both
# available to the subsequent CTest command.
add_custom_target(sjtuclaw_spine38_bridge
  DEPENDS sjtuclaw_spine38_bridge_library spine38_bridge_contract_test)
