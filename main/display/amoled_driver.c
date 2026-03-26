/**
 * amoled_driver.c — Waveshare ESP32-S3 1.43" AMOLED (SH8601/CO5300) driver.
 *
 * Initialises the 466×466 round QSPI AMOLED panel using the esp_lcd_sh8601
 * component.  Reads the panel IC ID via bit-bang SPI first so that the
 * correct init command sequence is selected (SH8601 vs CO5300).
 *
 * Pin mapping (Waveshare ESP32-S3 1.43" AMOLED):
 *   QSPI CS    → GPIO9
 *   QSPI CLK   → GPIO10
 *   QSPI D0    → GPIO11
 *   QSPI D1    → GPIO12
 *   QSPI D2    → GPIO13
 *   QSPI D3    → GPIO14
 *   LCD RESET  → GPIO21
 *   POWER EN   → GPIO42
 */

#include "display/amoled_driver.h"
#include "mimi_config.h"

#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "driver/spi_master.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_vendor.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_sh8601.h"
#include "esp_log.h"
#include "esp_err.h"
#include "read_lcd_id_bsp.h"

static const char *TAG = "amoled";

/* ── Pin definitions (Waveshare ESP32-S3 1.43" AMOLED) ─────────────────── */
#define LCD_HOST                SPI2_HOST
#define PIN_LCD_CS              MIMI_LCD_PIN_CS
#define PIN_LCD_CLK             MIMI_LCD_PIN_CLK
#define PIN_LCD_D0              MIMI_LCD_PIN_D0
#define PIN_LCD_D1              MIMI_LCD_PIN_D1
#define PIN_LCD_D2              MIMI_LCD_PIN_D2
#define PIN_LCD_D3              MIMI_LCD_PIN_D3
#define PIN_LCD_RST             MIMI_LCD_PIN_RST
#define PIN_LCD_PWREN           MIMI_LCD_PIN_PWREN

#define LCD_H_RES               MIMI_LCD_H_RES
#define LCD_V_RES               MIMI_LCD_V_RES
#define LCD_BIT_PER_PIXEL       16   /* RGB565 */

/* Panel IC IDs read from the hardware */
#define SH8601_ID               0x86
#define CO5300_ID               0xFF

/* ── State ───────────────────────────────────────────────────────────────── */
static esp_lcd_panel_handle_t s_panel = NULL;
static uint8_t s_lcd_id              = 0x00;

/* ── SH8601 init command sequence ────────────────────────────────────────── */
static const sh8601_lcd_init_cmd_t sh8601_init_cmds[] = {
    {0x11, (uint8_t []){0x00}, 0,  120},  /* Sleep Out              */
    {0x44, (uint8_t []){0x01, 0xD1}, 2, 0},  /* Tear Scan Line         */
    {0x35, (uint8_t []){0x00}, 1,   0},  /* Tearing Effect ON      */
    {0x53, (uint8_t []){0x20}, 1,  10},  /* Write CTRL Display     */
    {0x51, (uint8_t []){0x00}, 1,  10},  /* Write Display Bright 0 */
    {0x29, (uint8_t []){0x00}, 0,  10},  /* Display On             */
    {0x51, (uint8_t []){0xFF}, 1,   0},  /* Max Brightness         */
};

/* ── CO5300 init command sequence ────────────────────────────────────────── */
static const sh8601_lcd_init_cmd_t co5300_init_cmds[] = {
    {0x11, (uint8_t []){0x00}, 0,  80},  /* Sleep Out              */
    {0xC4, (uint8_t []){0x80}, 1,   0},  /* Display Mode           */
    {0x53, (uint8_t []){0x20}, 1,   1},  /* Write CTRL Display     */
    {0x63, (uint8_t []){0xFF}, 1,   1},  /* Write CABc Minimum     */
    {0x51, (uint8_t []){0x00}, 1,   1},  /* Write Display Bright 0 */
    {0x29, (uint8_t []){0x00}, 0,  10},  /* Display On             */
    {0x51, (uint8_t []){0xFF}, 1,   0},  /* Max Brightness         */
};

/* ── Public API ──────────────────────────────────────────────────────────── */

esp_err_t amoled_init(void)
{
    ESP_LOGI(TAG, "Initialising AMOLED display...");

    /* 1. Power enable */
    gpio_config_t pwr_cfg = {
        .mode         = GPIO_MODE_OUTPUT,
        .pin_bit_mask = 1ULL << PIN_LCD_PWREN,
        .pull_up_en   = GPIO_PULLUP_ENABLE,
    };
    ESP_ERROR_CHECK(gpio_config(&pwr_cfg));
    gpio_set_level(PIN_LCD_PWREN, 1);
    vTaskDelay(pdMS_TO_TICKS(100));

    /* 2. Read LCD panel IC ID (bit-bang SPI, before QSPI bus init) */
    s_lcd_id = read_lcd_id();
    ESP_LOGI(TAG, "LCD panel ID: 0x%02x (%s)",
             s_lcd_id,
             (s_lcd_id == SH8601_ID) ? "SH8601" : "CO5300");

    /* 3. Initialise QSPI bus */
    const spi_bus_config_t buscfg = SH8601_PANEL_BUS_QSPI_CONFIG(
        PIN_LCD_CLK,
        PIN_LCD_D0,
        PIN_LCD_D1,
        PIN_LCD_D2,
        PIN_LCD_D3,
        LCD_H_RES * LCD_V_RES * LCD_BIT_PER_PIXEL / 8
    );
    ESP_ERROR_CHECK(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO));

    /* 4. Create panel IO */
    esp_lcd_panel_io_handle_t io_handle = NULL;
    const esp_lcd_panel_io_spi_config_t io_config =
        SH8601_PANEL_IO_QSPI_CONFIG(PIN_LCD_CS, NULL, NULL);
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi(
        (esp_lcd_spi_bus_handle_t)LCD_HOST, &io_config, &io_handle));

    /* 5. Select init command table based on panel ID */
    sh8601_vendor_config_t vendor_config = {0};
    vendor_config.flags.use_qspi_interface = 1;
    if (s_lcd_id == SH8601_ID) {
        vendor_config.init_cmds      = sh8601_init_cmds;
        vendor_config.init_cmds_size = sizeof(sh8601_init_cmds)
                                     / sizeof(sh8601_init_cmds[0]);
    } else {
        vendor_config.init_cmds      = co5300_init_cmds;
        vendor_config.init_cmds_size = sizeof(co5300_init_cmds)
                                     / sizeof(co5300_init_cmds[0]);
    }

    /* 6. Create SH8601 panel */
    const esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num  = PIN_LCD_RST,
        .rgb_ele_order   = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel  = LCD_BIT_PER_PIXEL,
        .vendor_config   = &vendor_config,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_sh8601(io_handle, &panel_config, &s_panel));

    /* 7. Reset, init, turn on */
    ESP_ERROR_CHECK(esp_lcd_panel_reset(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

    ESP_LOGI(TAG, "AMOLED display ready (%dx%d)", LCD_H_RES, LCD_V_RES);
    return ESP_OK;
}

esp_lcd_panel_handle_t amoled_get_panel(void)
{
    return s_panel;
}

void amoled_power(bool on)
{
    if (s_panel) {
        esp_lcd_panel_disp_on_off(s_panel, on);
    }
}
