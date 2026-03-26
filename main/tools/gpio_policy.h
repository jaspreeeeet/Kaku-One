#pragma once

#include <stdbool.h>
#include <stddef.h>

/* GPIO defaults for ESP32-S3 Waveshare 1.43" AMOLED safe user-accessible pins.
 * Pins 9-14, 21, 42 are reserved for the AMOLED QSPI display and must not be
 * exposed to LLM GPIO tool operations. */
#define MIMI_GPIO_MIN_PIN       1
#define MIMI_GPIO_MAX_PIN       48
#define MIMI_GPIO_ALLOWED_CSV   "1,2,3,4,5,6,7,8,15,16,17,18,38,46,47,48"

/**
 * Check if a pin is allowed for user GPIO operations.
 * Validates against the allowlist or default range, and blocks
 * pins reserved for flash/PSRAM on ESP32.
 */
bool gpio_policy_pin_is_allowed(int pin);

/**
 * Write a human-readable hint if the pin is forbidden for a known reason.
 * Returns true if a hint was written (and the caller should return the error).
 */
bool gpio_policy_pin_forbidden_hint(int pin, char *result, size_t result_len);
