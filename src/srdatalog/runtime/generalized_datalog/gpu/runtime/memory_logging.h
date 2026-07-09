#pragma once

#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <exception>
#include <iostream>
#include <string>

#include <cuda_runtime.h>
#include "gpu/device_array.h"

namespace SRDatalog::GPU {

inline bool env_flag_enabled(const char* name) {
  const char* value = std::getenv(name);
  if (value == nullptr || *value == '\0') {
    return false;
  }
  return std::strcmp(value, "0") != 0 && std::strcmp(value, "false") != 0 &&
         std::strcmp(value, "FALSE") != 0 && std::strcmp(value, "off") != 0 &&
         std::strcmp(value, "OFF") != 0;
}

inline bool gpu_memory_log_enabled() {
  return env_flag_enabled("SRDATALOG_GPU_MEM_LOG");
}

inline bool gpu_memory_detail_enabled() {
  return env_flag_enabled("SRDATALOG_GPU_MEM_LOG_DETAIL");
}

inline bool gpu_memory_detail_step_enabled(int step) {
  if (!gpu_memory_detail_enabled()) {
    return false;
  }

  const char* filter = std::getenv("SRDATALOG_GPU_MEM_LOG_DETAIL_STEPS");
  if (filter == nullptr || *filter == '\0') {
    return true;
  }

  const char* p = filter;
  while (*p != '\0') {
    while (*p == ',' || *p == ' ') {
      ++p;
    }
    char* end = nullptr;
    long start = std::strtol(p, &end, 10);
    if (end == p) {
      break;
    }
    long stop = start;
    if (*end == '-') {
      char* range_end = nullptr;
      long parsed_stop = std::strtol(end + 1, &range_end, 10);
      if (range_end != end + 1) {
        stop = parsed_stop;
        end = range_end;
      }
    }
    if (step >= start && step <= stop) {
      return true;
    }
    p = end;
    while (*p != '\0' && *p != ',') {
      ++p;
    }
  }
  return false;
}

inline bool gpu_memory_detail_label_enabled(const char* label) {
  const char* filter = std::getenv("SRDATALOG_GPU_MEM_LOG_DETAIL_LABELS");
  if (filter == nullptr || *filter == '\0') {
    return true;
  }
  if (label == nullptr) {
    return false;
  }

  const char* p = filter;
  while (*p != '\0') {
    while (*p == ',' || *p == ' ') {
      ++p;
    }
    const char* start = p;
    while (*p != '\0' && *p != ',') {
      ++p;
    }
    std::string token(start, static_cast<std::size_t>(p - start));
    if (!token.empty() && std::string(label).find(token) != std::string::npos) {
      return true;
    }
  }
  return false;
}

inline bool gpu_memory_detail_count_enabled(int step) {
  const char* value = std::getenv("SRDATALOG_GPU_MEM_LOG_DETAIL_MAX_PER_STEP");
  if (value == nullptr || *value == '\0') {
    return true;
  }
  char* end = nullptr;
  long max_per_step = std::strtol(value, &end, 10);
  if (end == value || max_per_step <= 0) {
    return true;
  }

  static int last_step = -1;
  static long count_for_step = 0;
  if (step != last_step) {
    last_step = step;
    count_for_step = 0;
  }
  if (count_for_step >= max_per_step) {
    return false;
  }
  ++count_for_step;
  return true;
}

inline void log_gpu_memory(const char* label) {
  if (!gpu_memory_log_enabled()) {
    return;
  }

  if (env_flag_enabled("SRDATALOG_GPU_MEM_LOG_SYNC")) {
    cudaError_t sync_err = cudaDeviceSynchronize();
    if (sync_err != cudaSuccess) {
      std::cerr << "[gpu-mem] label=" << label
                << " cudaDeviceSynchronize=" << cudaGetErrorString(sync_err) << std::endl;
    }
  }

  std::size_t free_bytes = 0;
  std::size_t total_bytes = 0;
  cudaError_t err = cudaMemGetInfo(&free_bytes, &total_bytes);
  if (err != cudaSuccess) {
    std::cerr << "[gpu-mem] label=" << label
              << " cudaMemGetInfo=" << cudaGetErrorString(err) << std::endl;
    return;
  }

  const std::size_t mib = 1024ULL * 1024ULL;
  const std::size_t total_mib = total_bytes / mib;
  const std::size_t free_mib = free_bytes / mib;
  const std::size_t used_mib = total_mib - free_mib;

  RMMMemoryStats rmm_stats{};
  try {
    rmm_stats = get_rmm_memory_stats();
  } catch (const std::exception& e) {
    std::cout << "[gpu-mem] label=" << label << " used_mib=" << used_mib
              << " free_mib=" << free_mib << " total_mib=" << total_mib
              << " rmm_stats_error=\"" << e.what() << "\"" << std::endl;
    return;
  }

  std::cout << "[gpu-mem] label=" << label << " used_mib=" << used_mib
            << " free_mib=" << free_mib << " total_mib=" << total_mib
            << " rmm_stats=" << (rmm_stats.stats_enabled ? 1 : 0)
            << " rmm_current_bytes=" << rmm_stats.current_bytes
            << " rmm_current_mib=" << (rmm_stats.current_bytes / mib)
            << " rmm_peak_bytes=" << rmm_stats.peak_bytes
            << " rmm_peak_mib=" << (rmm_stats.peak_bytes / mib)
            << " rmm_total_allocated_bytes=" << rmm_stats.total_bytes
            << " rmm_total_allocated_mib=" << (rmm_stats.total_bytes / mib)
            << " rmm_pool_bytes=" << rmm_stats.pool_size_bytes
            << " rmm_pool_mib=" << (rmm_stats.pool_size_bytes / mib)
            << " rmm_current_allocs=" << rmm_stats.current_allocations
            << " rmm_peak_allocs=" << rmm_stats.peak_allocations << std::endl;
}

inline void log_gpu_memory_detail(int step, const char* label) {
  if (!gpu_memory_detail_step_enabled(step)) {
    return;
  }
  if (!gpu_memory_detail_label_enabled(label)) {
    return;
  }
  if (!gpu_memory_detail_count_enabled(step)) {
    return;
  }
  log_gpu_memory(label);
}

}  // namespace SRDatalog::GPU
