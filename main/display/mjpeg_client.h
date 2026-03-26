#pragma once

#include "esp_err.h"
#include <stdint.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * Callback type invoked with each decoded JPEG frame from the MJPEG stream.
 *
 * @param jpeg_data   Pointer to raw JPEG bytes (valid only during callback)
 * @param jpeg_len    Length of JPEG data in bytes
 */
typedef void (*mjpeg_frame_cb_t)(const uint8_t *jpeg_data, size_t jpeg_len);

/**
 * Initialize the MJPEG client.
 * Reads the server URL from NVS (key: expr_server_url).
 * Falls back to MIMI_EXPR_SERVER_URL defined in mimi_config.h.
 *
 * @param frame_cb  Called for every received JPEG frame. May be NULL (frames discarded).
 * @return ESP_OK on success
 */
esp_err_t mjpeg_client_init(mjpeg_frame_cb_t frame_cb);

/**
 * Start the MJPEG streaming task (connects and reads frames continuously).
 * Must call mjpeg_client_init() first.
 */
void mjpeg_client_start(void);

/**
 * Stop the MJPEG streaming task.
 */
void mjpeg_client_stop(void);

/**
 * Get the currently configured server base URL.
 * @return URL string (e.g. "http://192.168.1.10:8000")
 */
const char *mjpeg_client_get_server_url(void);

/**
 * Set and persist the server base URL to NVS.
 * Takes effect on next reconnect.
 */
esp_err_t mjpeg_client_set_server_url(const char *url);

#ifdef __cplusplus
}
#endif
