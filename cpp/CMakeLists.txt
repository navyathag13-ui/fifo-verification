cmake_minimum_required(VERSION 3.20)
project(fifo_cpp_model LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Build with a known-bad model to prove the tests catch it:
#   cmake -B build-bug -DFIFO_PLANTED_BUG=WRAP_BIT   (or PARTIAL_RESET)
set(FIFO_PLANTED_BUG "" CACHE STRING "Plant a known bug: WRAP_BIT or PARTIAL_RESET")

include(FetchContent)
FetchContent_Declare(
  googletest
  URL https://github.com/google/googletest/archive/refs/tags/v1.15.2.tar.gz
  DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(googletest)

add_executable(fifo_tests
  tests/test_pointer_fifo.cpp
  tests/test_random_vs_reference.cpp
  tests/test_gray.cpp
)
target_include_directories(fifo_tests PRIVATE include)
target_compile_options(fifo_tests PRIVATE -Wall -Wextra -Wpedantic -Werror)
if(FIFO_PLANTED_BUG)
  target_compile_definitions(fifo_tests PRIVATE FIFO_PLANTED_BUG_${FIFO_PLANTED_BUG})
endif()
target_link_libraries(fifo_tests PRIVATE GTest::gtest_main)

enable_testing()
include(GoogleTest)
gtest_discover_tests(fifo_tests)
