#pragma once

/**
 * amoled_driver.h — Waveshare ESP32-S3 1.43" AMOLED display driver.
 *
 * Initialises the SH8601/CO5300 QSPI AMOLED panel (466×466 round) and exposes
 * the esp_lcd_panel_handle for direct frame rendering via
 * esp_lcd_panel_draw_bitmap().
 *
 * Usage:
 *   ESP_ERROR_CHECK(amoled_init());
 *   esp_lcd_panel_handle_t panel = amoled_get_panel();
 *   // ... decode JPEG into rgb565 buffer ...
 *   esp_lcd_panel_draw_bitmap(panel, 0, 0, 466, 466, rgb565_buf);
 */

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialise the AMOLED display.
 *
 * - Reads LCD panel ID (SH8601=0x86 or CO5300=0xFF) via bit-bang SPI.
 * - Enables power rail on GPIO42.
 * - Initialises SPI2 bus in QSPI mode (CS=9, CLK=10, D0-D3=11-14).
 * - Creates esp_lcd panel, resets it, runs init sequence, turns display on.
 *
 * Must be called before any drawing or frame_renderer_init().
 *
 * @return ESP_OK on success, error code on hardware failure.
 */
esp_err_t amoled_init(void);

/**
 * Return the initialised panel handle.
 * Valid only after a successful amoled_init() call.
 */
esp_lcd_panel_handle_t amoled_get_panel(void);

/**
 * Turn the display on or off (backlight / display-on command).
 */
void amoled_power(bool on);

#ifdef __cplusplus
}
#endif
