#pragma once

/**
 * frame_renderer.h — JPEG → RGB565 → AMOLED frame rendering pipeline.
 *
 * Implements the mjpeg_frame_cb_t callback expected by mjpeg_client.
 * On each call it:
 *   1. Decodes the JPEG bytes using the ESP32-S3 ROM tjpgd decoder.
 *   2. Converts RGB888 → RGB565 (with byte-swap for SPI endianness).
 *   3. Pushes the decoded framebuffer to the AMOLED via
 *      esp_lcd_panel_draw_bitmap().
 *
 * Double-buffered: one buffer is rendered while the other is decoded into,
 * preventing screen tearing.  Both buffers are allocated in PSRAM.
 */

#include "esp_err.h"
#include "esp_lcd_panel_ops.h"
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Initialise the frame renderer.
 *
 * Allocates two 466×466×2 = ~434 KB framebuffers in PSRAM and a 4 KB
 * tjpgd work buffer in internal SRAM.
 *
 * @param panel  Initialised LCD panel handle (from amoled_get_panel()).
 * @return ESP_OK, or ESP_ERR_NO_MEM if allocations fail.
 */
esp_err_t frame_renderer_init(esp_lcd_panel_handle_t panel);

/**
 * Decode a JPEG frame and push it to the AMOLED display.
 *
 * This is the mjpeg_frame_cb_t callback — pass it directly to
 * mjpeg_client_init():
 *
 *   mjpeg_client_init(frame_render_jpeg);
 *
 * @param jpeg_data  Pointer to raw JPEG bytes (valid only during this call).
 * @param jpeg_len   Number of bytes in jpeg_data.
 */
void frame_render_jpeg(const uint8_t *jpeg_data, size_t jpeg_len);

#ifdef __cplusplus
}
#endif
