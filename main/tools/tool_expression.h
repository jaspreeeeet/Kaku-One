#pragma once

#include "esp_err.h"
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialize the expression tool.
 * Reads server URL from the MJPEG client (shared NVS key).
 */
esp_err_t tool_expression_init(void);

/**
 * Claude tool handler — set_expression.
 *
 * Input JSON:  {"expression": "<name>", "intensity": <0.0-1.0>}
 * Output JSON: {"status": "ok", "expression": "<name>"}
 *          or: {"status": "error", "message": "<reason>"}
 */
esp_err_t tool_expression_execute(const char *input_json, char *output, size_t output_size);

#ifdef __cplusplus
}
#endif
