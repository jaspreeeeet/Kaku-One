/**
 * mjpeg_client.c — Frame-polling client for MimiClaw expression server.
 *
 * Instead of persistent MJPEG streaming (which fails on serverless platforms
 * like Vercel), this fetches individual JPEG frames via HTTP GET requests.
 *
 * Flow:
 *   1. GET /mimiclaw/expression → current expression name + frame count
 *   2. GET /mimiclaw/frame?expression=X&index=N → single JPEG frame
 *   3. Invoke frame callback (decode → display)
 *   4. Delay to maintain target FPS, repeat
 *
 * A single esp_http_client with keep-alive reuses the TLS session across
 * all requests to minimise handshake overhead.
 */

#include "display/mjpeg_client.h"
#include "mimi_config.h"

#include <string.h>
#include <stdlib.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "esp_crt_bundle.h"
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "cJSON.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "mjpeg_client";

/* ── configuration ──────────────────────────────────────────────────────── */

#define NVS_NS                  "mimi_disp"
#define NVS_KEY_SERVER_URL      "expr_srv_url"

/* Target frames per second */
#define TARGET_FPS              12
#define FRAME_DELAY_MS          (1000 / TARGET_FPS)

/* Poll server for expression changes every N frames (~2 s) */
#define EXPR_POLL_INTERVAL      (TARGET_FPS * 2)

/* Maximum JPEG frame size (80 KB — 466×466 quality 82) */
#define MAX_FRAME_SIZE          (80 * 1024)

/* Buffer for small JSON responses */
#define JSON_BUF_SIZE           512

/* Delay after persistent errors before reconnecting */
#define RECONNECT_DELAY_MS      3000

/* Task config */
#define MJPEG_TASK_STACK        (8 * 1024)
#define MJPEG_TASK_PRIO         2
#define MJPEG_TASK_CORE         1


/* ── state ───────────────────────────────────────────────────────────────── */

static char             s_server_url[256] = {0};
static mjpeg_frame_cb_t s_frame_cb        = NULL;
static TaskHandle_t     s_task_handle     = NULL;
static volatile bool    s_running         = false;

/* Animation state */
static char    s_expression[32]  = "idle";
static int     s_frame_count     = 145;
static bool    s_loop            = true;
static int     s_frame_index     = 0;


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


/* ── generic HTTP event handler — accumulates response into a buffer ───── */

typedef struct {
    uint8_t *buf;
    size_t   len;
    size_t   cap;
} http_buf_t;

static http_buf_t s_resp;                       /* shared, swapped before each request */

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    http_buf_t *r = (http_buf_t *)evt->user_data;
    if (evt->event_id == HTTP_EVENT_ON_DATA && r) {
        size_t space = r->cap - r->len;
        size_t n = (size_t)evt->data_len < space ? (size_t)evt->data_len : space;
        if (n > 0) {
            memcpy(r->buf + r->len, evt->data, n);
            r->len += n;
        }
    }
    return ESP_OK;
}


/* ── poll expression state ─────────────────────────────────────────────── */

static bool poll_expression(esp_http_client_handle_t client, char *json_buf)
{
    char url[300];
    snprintf(url, sizeof(url), "%s/mimiclaw/expression", s_server_url);
    esp_http_client_set_url(client, url);

    /* Point shared buffer at the JSON scratch space */
    s_resp.buf = (uint8_t *)json_buf;
    s_resp.len = 0;
    s_resp.cap = JSON_BUF_SIZE;

    esp_err_t err = esp_http_client_perform(client);
    int status = esp_http_client_get_status_code(client);

    if (err != ESP_OK || status != 200) {
        ESP_LOGW(TAG, "Expression poll failed: err=%s status=%d",
                 esp_err_to_name(err), status);
        return false;
    }

    json_buf[s_resp.len < JSON_BUF_SIZE ? s_resp.len : JSON_BUF_SIZE - 1] = '\0';

    cJSON *root = cJSON_Parse(json_buf);
    if (!root) return false;

    bool changed = false;

    cJSON *j_expr   = cJSON_GetObjectItem(root, "expression");
    cJSON *j_frames = cJSON_GetObjectItem(root, "frames");
    cJSON *j_loop   = cJSON_GetObjectItem(root, "loop");

    if (cJSON_IsString(j_expr) && j_expr->valuestring) {
        if (strcmp(s_expression, j_expr->valuestring) != 0) {
            strlcpy(s_expression, j_expr->valuestring, sizeof(s_expression));
            s_frame_index = 0;
            changed = true;
            ESP_LOGI(TAG, "Expression → %s", s_expression);
        }
    }
    if (cJSON_IsNumber(j_frames)) s_frame_count = j_frames->valueint;
    if (cJSON_IsBool(j_loop))     s_loop = cJSON_IsTrue(j_loop);

    cJSON_Delete(root);
    return changed;
}


/* ── frame polling loop ────────────────────────────────────────────────── */

static void frame_poll_loop(void)
{
    ESP_LOGI(TAG, "Frame polling start: %s  target %d FPS", s_server_url, TARGET_FPS);

    /* Allocate frame buffer in PSRAM */
    uint8_t *frame_buf = (uint8_t *)heap_caps_malloc(MAX_FRAME_SIZE,
                              MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (!frame_buf) frame_buf = (uint8_t *)malloc(MAX_FRAME_SIZE);
    if (!frame_buf) {
        ESP_LOGE(TAG, "Failed to allocate frame buffer");
        return;
    }

    char json_buf[JSON_BUF_SIZE];

    /* One HTTP client for all requests — keep-alive reuses TLS session */
    char init_url[350];
    snprintf(init_url, sizeof(init_url), "%s/mimiclaw/expression", s_server_url);

    esp_http_client_config_t cfg = {
        .url               = init_url,
        .timeout_ms        = 8000,
        .buffer_size       = 4096,
        .buffer_size_tx    = 1024,
        .keep_alive_enable = true,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .event_handler     = http_event_handler,
        .user_data         = &s_resp,
    };

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) {
        ESP_LOGE(TAG, "HTTP client init failed");
        heap_caps_free(frame_buf);
        return;
    }

    /* Initial expression poll */
    poll_expression(client, json_buf);

    int poll_counter = 0;
    int error_count  = 0;

    while (s_running) {
        int64_t t0 = esp_timer_get_time();

        /* ── periodically check expression ─────────────────────────── */
        if (++poll_counter >= EXPR_POLL_INTERVAL) {
            poll_expression(client, json_buf);
            poll_counter = 0;
        }

        /* ── fetch one JPEG frame ──────────────────────────────────── */
        char frame_url[350];
        snprintf(frame_url, sizeof(frame_url),
                 "%s/mimiclaw/frame?expression=%s&index=%d",
                 s_server_url, s_expression, s_frame_index);
        esp_http_client_set_url(client, frame_url);

        s_resp.buf = frame_buf;
        s_resp.len = 0;
        s_resp.cap = MAX_FRAME_SIZE;

        esp_err_t err = esp_http_client_perform(client);
        int status = esp_http_client_get_status_code(client);

        if (err == ESP_OK && status == 200 && s_resp.len > 0) {
            error_count = 0;

            /* Deliver frame */
            if (s_frame_cb) {
                s_frame_cb(frame_buf, s_resp.len);
            }

            /* Advance index */
            s_frame_index++;
            if (s_loop) {
                if (s_frame_count > 0) s_frame_index %= s_frame_count;
            } else {
                if (s_frame_count > 0 && s_frame_index >= s_frame_count)
                    s_frame_index = s_frame_count - 1;
            }

            /* Maintain target FPS */
            int64_t elapsed_us = esp_timer_get_time() - t0;
            int delay = FRAME_DELAY_MS - (int)(elapsed_us / 1000);
            vTaskDelay(pdMS_TO_TICKS(delay > 1 ? delay : 1));

        } else {
            ESP_LOGW(TAG, "Frame fetch failed: err=%s status=%d len=%d",
                     esp_err_to_name(err), status, (int)s_resp.len);
            error_count++;

            /* Exponential back-off (1 s → 5 s max) */
            int backoff = error_count * 1000;
            if (backoff > 5000) backoff = 5000;
            vTaskDelay(pdMS_TO_TICKS(backoff));

            if (error_count >= 10) {
                ESP_LOGW(TAG, "Too many errors — will reconnect");
                break;
            }
        }
    }

    esp_http_client_cleanup(client);
    heap_caps_free(frame_buf);
}


/* ── FreeRTOS task ───────────────────────────────────────────────────────── */

static void mjpeg_task(void *arg)
{
    while (s_running) {
        if (strlen(s_server_url) == 0) {
            ESP_LOGW(TAG, "No server URL configured");
            vTaskDelay(pdMS_TO_TICKS(5000));
            continue;
        }

        frame_poll_loop();

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

    ESP_LOGI(TAG, "Frame-poll client init — server: %s",
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
    ESP_LOGI(TAG, "Frame-poll client task started");
}

void mjpeg_client_stop(void)
{
    s_running = false;
    ESP_LOGI(TAG, "Frame-poll client stop requested");
}
