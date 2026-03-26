/**
 * frame_renderer.c — JPEG → RGB565 → AMOLED frame rendering pipeline.
 *
 * Uses the ESP32-S3 ROM-resident tiny JPEG decoder (tjpgd) — no external
 * library required.  Two framebuffers are allocated in PSRAM (double-
 * buffered) to prevent screen tearing: one buffer is pushed to the display
 * while the next frame is decoded into the other.
 *
 * Because SPI DMA cannot reliably read directly from PSRAM on ESP32-S3,
 * the decoded frame is sent to the display in strips via a small DMA-capable
 * bounce buffer in internal SRAM (same pattern LVGL uses in the reference
 * project: E:\\Rajeev\\07_LVGL_Test).
 *
 * This file implements the mjpeg_frame_cb_t callback (frame_render_jpeg)
 * which is passed directly to mjpeg_client_init().
 */

#include "display/frame_renderer.h"
#include "mimi_config.h"

#include <string.h>
#include "esp_log.h"
#include "esp_err.h"
#include "esp_heap_caps.h"
#include "rom/tjpgd.h"

static const char *TAG = "frame_renderer";

/* ── Dimensions & buffer sizes ───────────────────────────────────────────── */
#define FRAME_W          MIMI_LCD_H_RES
#define FRAME_H          MIMI_LCD_V_RES
#define BYTES_PER_PIXEL  2   /* RGB565 */
#define FRAME_BUF_SIZE   (FRAME_W * FRAME_H * BYTES_PER_PIXEL)  /* ~434 KB */
#define WORK_BUF_SIZE    4096

/* Strip height for DMA bounce-buffer transfers.
 * 466 × 16 × 2 = 14,912 bytes per strip — fits comfortably in internal DMA
 * memory while keeping the number of SPI transactions reasonable (~30 strips). */
#define STRIP_H          16
#define STRIP_BUF_SIZE   (FRAME_W * STRIP_H * BYTES_PER_PIXEL)

/* ── State ───────────────────────────────────────────────────────────────── */
static esp_lcd_panel_handle_t s_panel         = NULL;
static uint8_t               *s_buf[2]        = {NULL, NULL};
static int                    s_back_idx      = 0;   /* decode into */
static int                    s_front_idx     = 1;   /* display from */
static uint8_t               *s_work          = NULL;
static uint8_t               *s_dma_buf       = NULL; /* DMA bounce buffer */

/* Context passed through jd->device during one decode call */
typedef struct {
    const uint8_t *data;
    size_t         len;
    size_t         pos;
} jpeg_src_t;

/* ── tjpgd callbacks ──────────────────────────────────────────────────────── */

/**
 * Input callback: feeds bytes from memory to tjpgd.
 * When buff == NULL the decoder wants to skip nbyte bytes.
 */
static UINT tjpgd_input_cb(JDEC *jd, BYTE *buff, UINT nbyte)
{
    jpeg_src_t *src = (jpeg_src_t *)jd->device;
    UINT available  = (UINT)(src->len - src->pos);
    if (nbyte > available) nbyte = available;

    if (buff) {
        memcpy(buff, src->data + src->pos, nbyte);
    }
    src->pos += nbyte;
    return nbyte;
}

/**
 * Output callback: receives decoded RGB888 block, converts to RGB565 with
 * byte-swap and writes it into the back framebuffer.
 *
 * ROM tjpgd always outputs RGB888 (JD_FORMAT = 0).
 * The SH8601 QSPI panel needs little-endian RGB565 on the SPI bus, which
 * after the SPI byte-swap means we must store the pixel big-endian in the
 * buffer (high byte first) — matching the CONFIG_LV_COLOR_16_SWAP behaviour
 * in the reference project.
 */
static UINT tjpgd_output_cb(JDEC *jd, void *bitmap, JRECT *rect)
{
    BYTE     *src  = (BYTE *)bitmap;
    uint16_t *dst  = (uint16_t *)s_buf[s_back_idx];

    UINT out_w = jd->width  >> jd->scale;
    UINT out_h = jd->height >> jd->scale;

    UINT dest_x = rect->left;
    UINT dest_y = rect->top;
    UINT width  = rect->right  - rect->left + 1;
    UINT height = rect->bottom - rect->top  + 1;

    UINT max_x = (dest_x + width  > out_w) ? (out_w - dest_x) : width;
    UINT max_y = (dest_y + height > out_h) ? (out_h - dest_y) : height;

    for (UINT y = 0; y < max_y; y++) {
        uint16_t *dst_row = dst + (dest_y + y) * out_w + dest_x;
        BYTE     *src_row = src + y * width * 3;

        for (UINT x = 0; x < max_x; x++) {
            uint8_t r = src_row[0];
            uint8_t g = src_row[1];
            uint8_t b = src_row[2];
            /* RGB888 → RGB565 */
            uint16_t color = ((r & 0xF8) << 8)
                           | ((g & 0xFC) << 3)
                           | (b >> 3);
            /* Byte-swap so the SPI peripheral sends bytes in the right order */
            *dst_row++ = (color << 8) | (color >> 8);
            src_row   += 3;
        }
    }
    return 1; /* 1 = continue decoding */
}

/**
 * Push the PSRAM framebuffer to the display in strips via an internal-RAM
 * DMA bounce buffer.  SPI DMA cannot reliably read from PSRAM directly on
 * ESP32-S3, so we memcpy each strip into DMA-capable memory first.
 */
static void flush_to_display(const uint8_t *framebuf)
{
    for (int y = 0; y < FRAME_H; y += STRIP_H) {
        int h = ((y + STRIP_H) > FRAME_H) ? (FRAME_H - y) : STRIP_H;
        size_t strip_bytes = (size_t)FRAME_W * h * BYTES_PER_PIXEL;

        /* Copy strip from PSRAM into DMA-capable internal buffer */
        memcpy(s_dma_buf,
               framebuf + ((size_t)y * FRAME_W * BYTES_PER_PIXEL),
               strip_bytes);

        /* Push strip to the display */
        esp_lcd_panel_draw_bitmap(s_panel, 0, y, FRAME_W, y + h, s_dma_buf);
    }
}

/* ── Public API ──────────────────────────────────────────────────────────── */

esp_err_t frame_renderer_init(esp_lcd_panel_handle_t panel)
{
    if (!panel) {
        ESP_LOGE(TAG, "panel handle is NULL");
        return ESP_ERR_INVALID_ARG;
    }
    s_panel = panel;

    /* Double-buffered framebuffers in PSRAM */
    for (int i = 0; i < 2; i++) {
        s_buf[i] = heap_caps_malloc(FRAME_BUF_SIZE,
                                    MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_buf[i]) {
            ESP_LOGE(TAG, "Failed to allocate framebuffer[%d] (%d bytes) in PSRAM",
                     i, FRAME_BUF_SIZE);
            return ESP_ERR_NO_MEM;
        }
        memset(s_buf[i], 0, FRAME_BUF_SIZE);
    }

    /* DMA bounce buffer in internal RAM for SPI strip transfers */
    s_dma_buf = heap_caps_malloc(STRIP_BUF_SIZE, MALLOC_CAP_DMA);
    if (!s_dma_buf) {
        ESP_LOGE(TAG, "Failed to allocate DMA bounce buffer (%d bytes)", STRIP_BUF_SIZE);
        return ESP_ERR_NO_MEM;
    }

    /* tjpgd work buffer in fast internal SRAM */
    s_work = heap_caps_malloc(WORK_BUF_SIZE,
                              MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!s_work) {
        ESP_LOGE(TAG, "Failed to allocate tjpgd work buffer (%d bytes)", WORK_BUF_SIZE);
        return ESP_ERR_NO_MEM;
    }

    ESP_LOGI(TAG, "Frame renderer ready (2 × %d KB PSRAM + %d KB DMA bounce)",
             FRAME_BUF_SIZE / 1024, STRIP_BUF_SIZE / 1024);
    return ESP_OK;
}

void frame_render_jpeg(const uint8_t *jpeg_data, size_t jpeg_len)
{
    if (!s_panel || !s_buf[0] || !s_buf[1] || !s_work || !s_dma_buf) {
        /* Not initialised yet — silently drop the frame */
        return;
    }

    jpeg_src_t src = {
        .data = jpeg_data,
        .len  = jpeg_len,
        .pos  = 0,
    };

    JDEC jd;
    JRESULT res = jd_prepare(&jd, tjpgd_input_cb, s_work, WORK_BUF_SIZE, &src);
    if (res != JDR_OK) {
        ESP_LOGW(TAG, "jd_prepare failed: %d", res);
        return;
    }

    /* Downscale if source is larger than our framebuffer (shouldn't happen
     * for 466×466 → 466×466, but guards against corrupt streams). */
    uint8_t scale = 0;
    while (((jd.width >> scale) > FRAME_W || (jd.height >> scale) > FRAME_H)
           && scale < 3) {
        scale++;
    }

    res = jd_decomp(&jd, tjpgd_output_cb, scale);
    if (res != JDR_OK) {
        ESP_LOGW(TAG, "jd_decomp failed: %d", res);
        return;
    }

    /* Push decoded back-buffer to display via DMA bounce buffer in strips */
    flush_to_display(s_buf[s_back_idx]);

    /* Swap buffers for the next frame */
    int tmp      = s_back_idx;
    s_back_idx   = s_front_idx;
    s_front_idx  = tmp;
}
