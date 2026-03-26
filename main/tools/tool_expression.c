/**
 * tool_expression.c — "set_expression" tool for Claude agent.
 *
 * When the LLM calls this tool, it HTTP POSTs to the expression server's
 * /expression endpoint, changing the character's face on the AMOLED display.
 *
 * POST /expression
 * Content-Type: application/json
 * {"expression": "happy", "intensity": 1.0}
 */

#include "tools/tool_expression.h"
#include "display/mjpeg_client.h"
#include "mimi_config.h"

#include <string.h>
#include <stdio.h>
#include "esp_log.h"
#include "esp_http_client.h"
#include "cJSON.h"

static const char *TAG = "tool_expr";

#define EXPRESSION_PATH  "/expression"
#define HTTP_TIMEOUT_MS  5000
#define RESP_BUF_SIZE    256

/* ── HTTP helper ─────────────────────────────────────────────────────────── */

static esp_err_t http_post_json(const char *url, const char *payload,
                                char *resp_buf, size_t resp_size)
{
    esp_http_client_config_t cfg = {
        .url        = url,
        .method     = HTTP_METHOD_POST,
        .timeout_ms = HTTP_TIMEOUT_MS,
    };

    esp_http_client_handle_t client = esp_http_client_init(&cfg);
    if (!client) return ESP_FAIL;

    esp_http_client_set_header(client, "Content-Type", "application/json");
    esp_http_client_set_post_field(client, payload, (int)strlen(payload));

    esp_err_t ret = esp_http_client_perform(client);
    if (ret == ESP_OK) {
        int status = esp_http_client_get_status_code(client);
        if (status != 200) {
            ESP_LOGW(TAG, "POST %s returned HTTP %d", url, status);
            ret = ESP_FAIL;
        } else if (resp_buf && resp_size > 0) {
            int64_t read_len = esp_http_client_get_content_length(client);
            if (read_len > 0 && read_len < (int64_t)resp_size) {
                esp_http_client_read_response(client, resp_buf, (int)read_len);
                resp_buf[read_len] = '\0';
            }
        }
    } else {
        ESP_LOGE(TAG, "HTTP POST failed: %s", esp_err_to_name(ret));
    }

    esp_http_client_cleanup(client);
    return ret;
}

/* ── public API ──────────────────────────────────────────────────────────── */

esp_err_t tool_expression_init(void)
{
    ESP_LOGI(TAG, "Expression tool ready — server: %s", mjpeg_client_get_server_url());
    return ESP_OK;
}

esp_err_t tool_expression_execute(const char *input_json, char *output, size_t output_size)
{
    /* Parse input */
    cJSON *root = cJSON_Parse(input_json);
    if (!root) {
        snprintf(output, output_size, "{\"status\":\"error\",\"message\":\"Invalid JSON\"}");
        return ESP_OK;
    }

    const char *expression = NULL;
    float intensity = 1.0f;

    cJSON *j_expr = cJSON_GetObjectItem(root, "expression");
    cJSON *j_intn = cJSON_GetObjectItem(root, "intensity");

    if (cJSON_IsString(j_expr) && j_expr->valuestring) {
        expression = j_expr->valuestring;
    }
    if (cJSON_IsNumber(j_intn)) {
        intensity = (float)j_intn->valuedouble;
    }

    if (!expression || strlen(expression) == 0) {
        cJSON_Delete(root);
        snprintf(output, output_size,
                 "{\"status\":\"error\",\"message\":\"'expression' field required\"}");
        return ESP_OK;
    }

    /* Build full URL */
    const char *base_url = mjpeg_client_get_server_url();
    if (!base_url || strlen(base_url) == 0) {
        cJSON_Delete(root);
        snprintf(output, output_size,
                 "{\"status\":\"error\",\"message\":\"Display server not configured. "
                 "Run: set_display_server http://<ip>:8000\"}");
        return ESP_OK;
    }

    char url[300];
    snprintf(url, sizeof(url), "%s%s", base_url, EXPRESSION_PATH);

    /* Build JSON payload */
    char payload[128];
    snprintf(payload, sizeof(payload),
             "{\"expression\":\"%s\",\"intensity\":%.2f}", expression, intensity);

    ESP_LOGI(TAG, "Setting expression: %s (intensity=%.2f)", expression, intensity);

    /* POST to server */
    char resp[RESP_BUF_SIZE] = {0};
    esp_err_t ret = http_post_json(url, payload, resp, sizeof(resp));

    cJSON_Delete(root);

    if (ret == ESP_OK) {
        snprintf(output, output_size,
                 "{\"status\":\"ok\",\"expression\":\"%s\"}", expression);
    } else {
        snprintf(output, output_size,
                 "{\"status\":\"error\",\"message\":\"Failed to reach display server\"}");
    }

    return ESP_OK;
}
