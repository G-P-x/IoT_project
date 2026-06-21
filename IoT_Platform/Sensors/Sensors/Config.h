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

// --- SOGLIE ANOMALIE (una sola soglia critica per sensore) ---
// Modifica questi valori in base al punto di deployment del nodo.
#define TEMP_THRESHOLD    60.0f    // gradi C — sopra questa temperatura: CRITICAL
#define SEISMIC_THRESHOLD      4.0f  // m/s2 — soglia critica
#define SEISMIC_CRITICAL_MIN   1     // letture consecutive sopra soglia per scattare l'allarme
                                     // 1 = qualsiasi picco; 3 = richiede attività prolungata (~15s)
#define AIR_THRESHOLD   10000.0f  // ppm CO2 — sopra questa concentrazione: CRITICAL

#endif