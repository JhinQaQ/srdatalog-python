/**
 * @file device_array_rmm_impl.h
 * @brief RMM implementation details for DeviceArray (host-only)
 *
 * This file contains RMM-specific implementation that should only be compiled
 * for host code to avoid spdlog consteval issues in device code.
 */

#pragma once

#ifndef __CUDA_ARCH__
#ifndef __HIP_DEVICE_COMPILE__

// Note: Requires LIBCUDACXX_ENABLE_EXPERIMENTAL_MEMORY_RESOURCE to be defined
// (defined in xmake.lua when nvidia or rocm config is enabled)

// Workaround for spdlog/fmt consteval issue with clang-cuda/clang-hip
// Use std::format instead of fmt to avoid consteval issues
#ifndef SPDLOG_USE_STD_FORMAT
#define SPDLOG_USE_STD_FORMAT
#endif

// Use GPU API abstraction instead of direct CUDA includes
#include "gpu/gpu_api.h"

// This file is host-only, so RMM/hipMM headers (which pull in spdlog) are safe here
// We need the full RMM headers here for pool_memory_resource and cuda_memory_resource types
// Note: hipMM maintains RMM API compatibility, so these headers work for both CUDA and HIP
#include <cstdlib>
#include <cstring>
#include <limits>
#include <memory>
#include <optional>
#include <rmm/cuda_device.hpp>  // For rmm::available_device_memory() - works with hipMM too
#include <rmm/mr/device/aligned_resource_adaptor.hpp>
#include <rmm/mr/device/cuda_memory_resource.hpp>  // hipMM maintains this API
#include <rmm/mr/device/per_device_resource.hpp>
#include <rmm/mr/device/pool_memory_resource.hpp>
#include <rmm/mr/device/statistics_resource_adaptor.hpp>
#include <stdexcept>
#include <string>
#include <utility>

namespace SRDatalog::GPU {

inline bool rmm_env_flag_enabled(const char* name) {
  const char* value = std::getenv(name);
  if (value == nullptr || *value == '\0') {
    return false;
  }
  return std::strcmp(value, "0") != 0 && std::strcmp(value, "false") != 0 &&
         std::strcmp(value, "FALSE") != 0 && std::strcmp(value, "off") != 0 &&
         std::strcmp(value, "OFF") != 0;
}

inline bool rmm_stats_log_enabled() {
  return rmm_env_flag_enabled("SRDATALOG_RMM_STATS_LOG") ||
         rmm_env_flag_enabled("SRDATALOG_GPU_MEM_LOG");
}

/**
 * @brief Configuration for RMM pool memory resource
 * @details Pool sizes can be configured via environment variables:
 *   - SRDATALOG_RMM_POOL_INITIAL_SIZE: Initial pool size in bytes (default: 1GB)
 *   - SRDATALOG_RMM_POOL_MAX_SIZE: Maximum pool size in bytes (default: unlimited)
 *     Set to 0 or use environment variable to specify a limit, otherwise unlimited
 * @note If environment variables are not set, uses default values (unlimited max size)
 */
namespace RMMConfig {
// Default pool sizes (can be overridden via environment variables)
constexpr std::size_t DEFAULT_INITIAL_SIZE = 1024ULL * 1024 * 1024;  // 1GB
// Default max size is unlimited (use a very large value that's a multiple of 256)
// Using UINT64_MAX rounded down to multiple of 256: 0xFFFFFFFFFFFFFE00
// RMM requires max_size to be a multiple of 256 bytes
constexpr std::size_t DEFAULT_MAX_SIZE = 0xFFFFFFFFFFFFFE00ULL;  // ~18 exabytes, multiple of 256

inline std::size_t get_initial_size() {
  const char* env = std::getenv("SRDATALOG_RMM_POOL_INITIAL_SIZE");
  if (env != nullptr) {
    return std::strtoull(env, nullptr, 0);
  }
  return DEFAULT_INITIAL_SIZE;
}

inline std::size_t get_max_size() {
  const char* env = std::getenv("SRDATALOG_RMM_POOL_MAX_SIZE");
  if (env != nullptr) {
    std::size_t value = std::strtoull(env, nullptr, 0);
    // Allow 0 to mean unlimited (use default unlimited value)
    if (value == 0) {
      return DEFAULT_MAX_SIZE;
    }
    // Round to nearest multiple of 256 (round down) - RMM requirement
    return (value / 256) * 256;
  }
  return DEFAULT_MAX_SIZE;  // Unlimited by default
}

inline std::optional<std::size_t> get_max_size_optional() {
  const char* env = std::getenv("SRDATALOG_RMM_POOL_MAX_SIZE");
  if (env != nullptr) {
    std::size_t value = std::strtoull(env, nullptr, 0);
    // Allow 0 or empty to mean unlimited (return std::nullopt)
    if (value == 0) {
      return std::nullopt;
    }
    // Round to nearest multiple of 256 (round down) - RMM requirement
    return std::make_optional((value / 256) * 256);
  }
  return std::nullopt;  // Unlimited by default (no max size limit)
}
}  // namespace RMMConfig

using SRDatalogRMMUpstream = rmm::mr::cuda_memory_resource;
using SRDatalogRMMPool = rmm::mr::pool_memory_resource<SRDatalogRMMUpstream>;
using SRDatalogRMMStats = rmm::mr::statistics_resource_adaptor<SRDatalogRMMPool>;

struct RMMResourceBundle {
  std::unique_ptr<SRDatalogRMMUpstream> upstream;
  std::unique_ptr<SRDatalogRMMPool> pool;
  std::unique_ptr<SRDatalogRMMStats> stats;

  [[nodiscard]] rmm::mr::device_memory_resource* current_resource() const {
    if (stats) {
      return stats.get();
    }
    return pool.get();
  }
};

inline RMMResourceBundle& get_gpu_rmm_resource_bundle() {
  static RMMResourceBundle bundle = []() {
    // Ensure GPU is initialized before accessing RMM/hipMM
    int current_device = -1;
    GPU_ERROR_T err = GPU_GET_DEVICE(&current_device);
    if (err != GPU_SUCCESS) {
      throw std::runtime_error(
          "get_gpu_rmm_resource_bundle: GPU not initialized. Call init_cuda() first. Error: " +
          std::string(GPU_GET_ERROR_STRING(err)));
    }

    auto upstream = std::make_unique<SRDatalogRMMUpstream>();

    // Get configured pool sizes (from environment variables or defaults)
    std::size_t initial_size = RMMConfig::get_initial_size();
    std::optional<std::size_t> max_size = RMMConfig::get_max_size_optional();

    // If max_size is nullopt, RMM lets the pool grow up to available device memory.
    auto pool = std::make_unique<SRDatalogRMMPool>(upstream.get(), initial_size, max_size);

    std::unique_ptr<SRDatalogRMMStats> stats;
    if (rmm_stats_log_enabled()) {
      stats = std::make_unique<SRDatalogRMMStats>(pool.get());
    }

    RMMResourceBundle result{std::move(upstream), std::move(pool), std::move(stats)};
    rmm::mr::set_current_device_resource(result.current_resource());
    return result;
  }();
  return bundle;
}

/**
 * @brief Thread-safe singleton that provides a global GPU pool memory resource
 * @note GPU (CUDA or HIP) must be initialized before this is called (call init_cuda() first)
 * @note This function is host-only (allocation happens on host)
 * @note The pool is also set as the global per-device resource so all RMM/hipMM allocations use it
 */
inline rmm::mr::device_memory_resource* get_gpu_pool_memory_resource() {
  return get_gpu_rmm_resource_bundle().pool.get();
}

/**
 * @brief Current device memory resource to install in RMM.
 * @details When SRDATALOG_GPU_MEM_LOG or SRDATALOG_RMM_STATS_LOG is enabled before
 *          init_cuda(), this is an RMM statistics adaptor around the pool. Otherwise
 *          it is the pool itself.
 */
inline rmm::mr::device_memory_resource* get_gpu_current_memory_resource() {
  return get_gpu_rmm_resource_bundle().current_resource();
}

inline RMMMemoryStats get_rmm_memory_stats() {
  auto& bundle = get_gpu_rmm_resource_bundle();
  RMMMemoryStats out{};
  if (bundle.pool) {
    out.pool_available = true;
    out.pool_size_bytes = bundle.pool->pool_size();
  }
  if (bundle.stats) {
    out.stats_enabled = true;
    auto bytes = bundle.stats->get_bytes_counter();
    auto allocations = bundle.stats->get_allocations_counter();
    out.current_bytes = static_cast<std::size_t>(bytes.value);
    out.peak_bytes = static_cast<std::size_t>(bytes.peak);
    out.total_bytes = static_cast<std::size_t>(bytes.total);
    out.current_allocations = static_cast<std::size_t>(allocations.value);
    out.peak_allocations = static_cast<std::size_t>(allocations.peak);
    out.total_allocations = static_cast<std::size_t>(allocations.total);
  }
  return out;
}

/**
 * @brief Initialize and set up the global RMM pool memory resource
 * @note This should be called early in the program (typically in init_cuda())
 * @note This function is idempotent - safe to call multiple times
 */
inline void init_rmm_pool() {
  // Simply access the pool to trigger its initialization
  (void)get_gpu_pool_memory_resource();
}

/**
 * @brief Get the RMM pool memory resource as pool_memory_resource pointer for advanced operations
 * @return Pointer to the pool memory resource (can be used to call print() for memory reports)
 * @note This function is host-only
 */
inline rmm::mr::pool_memory_resource<rmm::mr::cuda_memory_resource>*
get_gpu_pool_memory_resource_typed() {
  return get_gpu_rmm_resource_bundle().pool.get();
}

/**
 * @brief Print RMM pool memory usage report
 * @note This function is host-only and intended for debugging/monitoring
 */
inline void print_rmm_memory_report() {
  auto* pool = get_gpu_pool_memory_resource_typed();
  if (pool != nullptr) {
    std::cout << "\n=== RMM Pool Memory Report ===" << std::endl;

    // Get GPU memory information
    auto const [free, total] = rmm::available_device_memory();
    std::cout << "GPU free memory: " << free << " bytes (" << (free / (1024.0 * 1024.0)) << " MB)"
              << std::endl;
    std::cout << "GPU total memory: " << total << " bytes (" << (total / (1024.0 * 1024.0))
              << " MB)" << std::endl;

    // Get pool size
    std::size_t pool_size = pool->pool_size();
    std::cout << "Pool size: " << pool_size << " bytes (" << (pool_size / (1024.0 * 1024.0))
              << " MB)" << std::endl;

// Try to call print() if RMM_DEBUG_PRINT is defined
#ifdef RMM_DEBUG_PRINT
    pool->print();
#else
    std::cout << "Note: Enable RMM_DEBUG_PRINT for detailed block information" << std::endl;
#endif

    std::cout << "==============================\n" << std::endl;
  }
}

}  // namespace SRDatalog::GPU

#endif  // __HIP_DEVICE_COMPILE__
#endif  // __CUDA_ARCH__
