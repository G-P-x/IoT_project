//11 6 2026
#ifndef CONFIG_H
#define CONFIG_H

// =====================================================
// CONFIG.H — Modifica solo questo file per configurare
// il sistema. Non toccare Sensors.ino o Sensors.h.
// =====================================================

// --- RETE WiFi ---
#define WIFI_SSID  "Mani Deïz"
#define WIFI_PASS  "rybe4250"

// --- GATEWAY (IP del PC nella rete corrente) ---
#define MQTT_HOST_ADDR  "10.98.201.225"
#define MQTT_PORT_NUM   1883

// --- TIMING ---
#define SEND_INTERVAL_MS    5000  // pubblica sensori ogni N ms
#define BUZZER_DURATION_MS  3000  // buzzer suona 3s poi si spegne automaticamente

// --- PIN ---
#define PIN_DHT        D4
#define PIN_MQ135_AO   A0
#define PIN_MQ135_DO   D7
#define PIN_MPU_INT    D5
#define PIN_BUZZER     D3

// --- SOGLIE ANOMALIE ---
#define TEMP_WARNING_C    40.0f
#define TEMP_CRITICAL_C   60.0f
#define SEISMIC_THRESHOLD 8.0f
#define AIR_WARMUP_THR    50
#define AIR_WARNING_PPM   5000.0f   // degassamento vulcanico anomalo
#define AIR_CRITICAL_PPM  10000.0f  // pericolo per la salute

#endif