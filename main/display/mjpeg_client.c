/**
 * mjpeg_client.c — HTTP MJPEG stream client for MimiClaw.
 *
 * Connects to the expression server's GET /stream endpoint (multipart/x-mixed-replace).
 * Parses the MIME boundary, extracts each JPEG frame, and invokes the user callback.
 *
 * Wire format produced by the FastAPI server:
 *   --frame\r\n
 *   Content-Type: image/jpeg\r\n
 *   Content-Length: <N>\r\n
 *   \r\n
 *   <N bytes of JPEG data>
 *   \r\n
 *   (repeat)
 */

#include "display/mjpeg_client.h"
#include "mimi_config.h"

#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_heap_caps.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "mjpeg_client";

/* ── configuration ──────────────────────────────────────────────────────── */

#define NVS_NS                  "mimi_disp"
#define NVS_KEY_SERVER_URL      "expr_srv_url"
#define STREAM_PATH             "/stream"

/* Read buffer for HTTP response body */
#define READ_BUF_SIZE           (4 * 1024)

/* Maximum JPEG frame size (80 KB — large enough for 466×466 quality 82) */
#define MAX_FRAME_SIZE          (80 * 1024)

/* Reconnect delay on error */
#define RECONNECT_DELAY_MS      3000

/* Task config */
#define MJPEG_TASK_STACK        (8 * 1024)
#define MJPEG_TASK_PRIO         4
#define MJPEG_TASK_CORE         0


/* ── state ───────────────────────────────────────────────────────────────── */

static char             s_server_url[256] = {0};
static mjpeg_frame_cb_t s_frame_cb        = NULL;
static TaskHandle_t     s_task_handle     = NULL;
static volatile bool    s_running         = false;

/* ── NVS helpers ─────────────────────────────────────────────────────────── */

static void load_server_url_from_nvs(void)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) return;

    size_t len = sizeof(s_server_url);
    nvs_get_str(h, NVS_KEY_SERVER_URL, s_server_url, &len);
    nvs_close(h);
}

esp_err_t mjpeg_client_set_server_url(const char *url)
{
    if (!url || strlen(url) == 0 || strlen(url) >= sizeof(s_server_url)) {
        return ESP_ERR_INVALID_ARG;
    }

    strlcpy(s_server_url, url, sizeof(s_server_url));

    nvs_handle_t h;
    esp_err_t ret = nvs_open(NVS_NS, NVS_READWRITE, &h);
    if (ret != ESP_OK) return ret;
    ret = nvs_set_str(h, NVS_KEY_SERVER_URL, url);
    if (ret == ESP_OK) ret = nvs_commit(h);
    nvs_close(h);

    ESP_LOGI(TAG, "Server URL saved: %s", url);
    return ret;
}

const char *mjpeg_client_get_server_url(void)
{
    return s_server_url;
}

/* ── MJPEG frame parser ───────────────────────────────────────────────────── */

/**
 * Search for a byte pattern in a buffer.
 * Returns pointer to first occurrence, or NULL.
 */
static const uint8_t *memmem_simple(const uint8_t *haystack, size_t hs_len,
                                    const uint8_t *needle,   size_t nd_len)
{
    if (nd_len == 0 || nd_len > hs_len) return NULL;
    for (size_t i = 0; i <= hs_len - nd_len; i++) {
        if (memcmp(haystack + i, needle, nd_len) == 0) return haystack + i;
    }
    return NULL;
}

/**
 * Extract the integer value of "Content-Length:" header from a header block.
 * header_block must be null-terminated.
 * Returns 0 if not found.
 */
static int parse_content_length(const char *header_block)
{
    const char *p = strcasestr(header_block, "Content-Length:");
    if (!p) return 0;
    p += strlen("Content-Length:");
    while (*p == ' ') p++;
    return atoi(p);
}

/**
 * Core streaming loop — runs while s_running is true.
 * Opens the HTTP connection, reads the multipart stream, invokes frame callback.
 */
static void mjpeg_stream_loop(void)
{
    char url[300];
    snprintf(url, sizeof(url), "%s%s", s_server_url, STREAM_PATH);

    ESP_LOGI(TAG, "Connecting to MJPEG stream: %s", url);

    esp_http_client_config_t cfg = {
        .url            = url,
        .timeout_ms     = 10000,
        .buffer_size    = READ_BUF_SIZE,
        .keep_alive_enable = true,
    };

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        ESP_LOGE(TAG, "Failed to create HTTP client");
        return;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "HTTP open failed: %s", esp_err_to_name(err));
        esp_http_client_cleanup(client);
        return;
    }

    int64_t content_len = esp_http_client_fetch_headers(client);
    (void)content_len;  /* Streaming — no total content length */

    int status = esp_http_client_get_status_code(client);
    if (status != 200) {
        ESP_LOGE(TAG, "HTTP status %d — expected 200", status);
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        return;
    }

    ESP_LOGI(TAG, "MJPEG stream connected (HTTP 200)");

    /* Allocate read buffer (stack would be too large) */
    uint8_t *read_buf = malloc(READ_BUF_SIZE);
    /* Allocate frame accumulator in PSRAM if available */
    uint8_t *frame_buf = (uint8_t *)heap_caps_malloc(MAX_FRAME_SIZE,
                             MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!frame_buf) {
        frame_buf = malloc(MAX_FRAME_SIZE);
    }

    if (!read_buf || !frame_buf) {
        ESP_LOGE(TAG, "Failed to allocate buffers");
        goto cleanup;
    }

    /* ── parser state machine ───────────────────────────────────────────── */
    /*
     * We maintain a "work buffer" of recently received bytes so we can detect
     * the --frame boundary and header block even when they span multiple reads.
     */
    static const uint8_t BOUNDARY[]   = "--frame\r\n";
    static const uint8_t HDR_END[]    = "\r\n\r\n";

    /* Work buffer for header parsing (boundaries + sub-headers fit in 512 B) */
    uint8_t  work[512];
    size_t   work_len = 0;
    bool     in_frame = false;    /* true: reading frame JPEG bytes */
    int      frame_content_len = 0;
    size_t   frame_bytes_read  = 0;

    while (s_running) {
        int rd = esp_http_client_read(client, (char *)read_buf, READ_BUF_SIZE);
        if (rd < 0) {
            ESP_LOGW(TAG, "Read error %d — reconnecting", rd);
            break;
        }
        if (rd == 0) {
            vTaskDelay(pdMS_TO_TICKS(5));
            continue;
        }

        size_t consumed = 0;
        while (consumed < (size_t)rd) {
            if (!in_frame) {
                /* ── Looking for --frame\r\n + headers ─────────────────── */
                /* Append incoming data to work buffer */
                size_t to_copy = (size_t)rd - consumed;
                if (work_len + to_copy > sizeof(work)) {
                    to_copy = sizeof(work) - work_len;
                }
                memcpy(work + work_len, read_buf + consumed, to_copy);
                work_len += to_copy;
                consumed += to_copy;

                /* Find boundary */
                const uint8_t *boundary_pos = memmem_simple(work, work_len,
                                                              BOUNDARY, sizeof(BOUNDARY) - 1);
                if (!boundary_pos) {
                    /* Keep last (sizeof(BOUNDARY)-1) bytes in case boundary spans reads */
                    size_t keep = sizeof(BOUNDARY) - 1;
                    if (work_len > keep) {
                        memmove(work, work + work_len - keep, keep);
                        work_len = keep;
                    }
                    continue;
                }

                /* Found boundary — advance past it */
                size_t after_boundary = (boundary_pos - work) + sizeof(BOUNDARY) - 1;

                /* Find end of sub-headers (\r\n\r\n) */
                const uint8_t *hdr_end = memmem_simple(work + after_boundary,
                                                        work_len - after_boundary,
                                                        HDR_END, sizeof(HDR_END) - 1);
                if (!hdr_end) {
                    /* Headers not fully received yet — keep work buffer */
                    if (after_boundary > 0) {
                        memmove(work, work + after_boundary, work_len - after_boundary);
                        work_len -= after_boundary;
                    }
                    continue;
                }

                /* Null-terminate the header block for string parsing */
                size_t hdr_len = (hdr_end - (work + after_boundary));
                char hdr_block[256] = {0};
                if (hdr_len < sizeof(hdr_block)) {
                    memcpy(hdr_block, work + after_boundary, hdr_len);
                }

                frame_content_len = parse_content_length(hdr_block);
                if (frame_content_len <= 0 || frame_content_len > MAX_FRAME_SIZE) {
                    ESP_LOGW(TAG, "Bad Content-Length: %d — skipping", frame_content_len);
                    /* Discard work buffer and continue searching */
                    work_len = 0;
                    continue;
                }

                /* Data after \r\n\r\n is the start of the JPEG frame */
                size_t data_start = (hdr_end - work) + sizeof(HDR_END) - 1;
                size_t leftover   = work_len - data_start;

                frame_bytes_read = 0;
                if (leftover > 0) {
                    size_t copy = leftover < (size_t)frame_content_len ? leftover : (size_t)frame_content_len;
                    memcpy(frame_buf, work + data_start, copy);
                    frame_bytes_read = copy;
                }

                work_len = 0;
                in_frame = true;

            } else {
                /* ── Accumulating JPEG frame bytes ────────────────────── */
                size_t need = (size_t)frame_content_len - frame_bytes_read;
                size_t avail = (size_t)rd - consumed;
                size_t copy  = avail < need ? avail : need;

                if (frame_bytes_read + copy <= MAX_FRAME_SIZE) {
                    memcpy(frame_buf + frame_bytes_read, read_buf + consumed, copy);
                }
                frame_bytes_read += copy;
                consumed         += copy;

                if (frame_bytes_read >= (size_t)frame_content_len) {
                    /* Full JPEG frame received — invoke callback */
                    if (s_frame_cb) {
                        s_frame_cb(frame_buf, (size_t)frame_content_len);
                    }
                    in_frame = false;
                    frame_bytes_read  = 0;
                    frame_content_len = 0;
                }
            }
        }
    }

cleanup:
    free(read_buf);
    if (frame_buf) {
        heap_caps_free(frame_buf);  /* safe even if allocated with malloc */
    }
    esp_http_client_close(client);
    esp_http_client_cleanup(client);
}

/* ── FreeRTOS task ───────────────────────────────────────────────────────── */

static void mjpeg_task(void *arg)
{
    while (s_running) {
        if (strlen(s_server_url) == 0) {
            ESP_LOGW(TAG, "No server URL configured. Use: set_display_server <url>");
            vTaskDelay(pdMS_TO_TICKS(5000));
            continue;
        }

        mjpeg_stream_loop();

        if (s_running) {
            ESP_LOGI(TAG, "Reconnecting in %d ms…", RECONNECT_DELAY_MS);
            vTaskDelay(pdMS_TO_TICKS(RECONNECT_DELAY_MS));
        }
    }

    ESP_LOGI(TAG, "MJPEG task stopped");
    s_task_handle = NULL;
    vTaskDelete(NULL);
}

/* ── public API ──────────────────────────────────────────────────────────── */

esp_err_t mjpeg_client_init(mjpeg_frame_cb_t frame_cb)
{
    s_frame_cb = frame_cb;

    /* Start with compile-time default */
    strlcpy(s_server_url, MIMI_EXPR_SERVER_URL, sizeof(s_server_url));

    /* Override with NVS value if present */
    load_server_url_from_nvs();

    ESP_LOGI(TAG, "MJPEG client init — server: %s",
             strlen(s_server_url) ? s_server_url : "(not configured)");
    return ESP_OK;
}

void mjpeg_client_start(void)
{
    if (s_task_handle) {
        ESP_LOGW(TAG, "Already running");
        return;
    }
    s_running = true;
    xTaskCreatePinnedToCore(
        mjpeg_task, "mjpeg_client",
        MJPEG_TASK_STACK, NULL,
        MJPEG_TASK_PRIO, &s_task_handle,
        MJPEG_TASK_CORE
    );
    ESP_LOGI(TAG, "MJPEG client task started");
}

void mjpeg_client_stop(void)
{
    s_running = false;
    ESP_LOGI(TAG, "MJPEG client stop requested");
}
