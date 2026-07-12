//11_07_2026

/*
 * CONFIG.H — File di configurazione del nodo IoT
 * ================================================
 * Unico file da modificare per adattare il nodo a un nuovo deployment.
 * Sensors.h e Sensors.ino non contengono valori hardcoded.
 *
 * Sezioni:
 *   1. Rete WiFi     — credenziali di accesso
 *   2. Gateway MQTT  — indirizzo broker e porta
 *   3. Timing        — intervalli di pubblicazione e durata LED
 *   4. Pin           — mappatura fisica dei componenti sul NodeMCU
 *   5. Soglie        — valori critici per ogni grandezza fisica
 */

#ifndef CONFIG_H          // Guardia di inclusione: evita doppia definizione
#define CONFIG_H          // se il file viene incluso piu' volte

// =====================================================
// CONFIG.H — Modifica solo questo file per configurare
// il sistema. Non toccare Sensors.ino o Sensors.h.
// =====================================================

// --- RETE WiFi ---
// Se la rete cambia (cambio hotspot/router), aggiornare solo qui.
#define WIFI_SSID  "Mani Deïz"        // Nome della rete WiFi (SSID)
#define WIFI_PASS  "rybe4250"         // Password della rete WiFi

// --- GATEWAY (IP del PC nella rete corrente) ---
// MQTT_HOST_ADDR: IP assegnato dal DHCP al PC gateway. Aggiornare se cambia.
// MQTT_PORT_NUM:  porta standard MQTT non cifrata (senza TLS).
#define MQTT_HOST_ADDR  "10.217.191.225"  // Indirizzo IP del broker Mosquitto
#define MQTT_PORT_NUM   1883              // Porta MQTT standard (non cifrata)

// --- TIMING ---
// SEND_INTERVAL_MS: ogni quanti ms il nodo pubblica tutti i sensori.
//   Valore piu' basso = maggiore risoluzione temporale ma piu' traffico.
// BUZZER_DURATION_MS: dopo questo tempo dalla ricezione di "alarm: 1",
//   il LED si spegne automaticamente (senza bisogno di un secondo comando).
#define SEND_INTERVAL_MS    5000   // Intervallo pubblicazione MQTT [ms] (5 secondi)
#define BUZZER_DURATION_MS  3000   // Durata accensione LED [ms] (3 secondi)

// --- PIN ---
// Mappatura dei componenti fisici sui pin del NodeMCU ESP8266.
#define PIN_DHT        D4   // GPIO2  — DHT11: linea dati single-wire
#define PIN_MQ135_AO   A0   // ADC0   — MQ-135: uscita analogica (0-1023)
#define PIN_MQ135_DO   D7   // GPIO13 — MQ-135: uscita digitale comparatore
#define PIN_MPU_INT    D5   // GPIO14 — MPU-6050: pin interrupt (non usato)
#define PIN_BUZZER     D3   // GPIO0  — LED di allarme (ex buzzer)

// --- SOGLIE ANOMALIE ---
// Valori oltre i quali ogni sensore genera severity "critical".
// Calibrare in base al punto di deployment sul vulcano.

#define TEMP_THRESHOLD        60.0f   // [gradi C]  — soglia temperatura: 60C e' conservativo
#define SEISMIC_THRESHOLD      4.0f   // [m/s^2]    — soglia scostamento dalla baseline
#define SEISMIC_CRITICAL_MIN   1      // [campioni] — letture consecutive sopra soglia (1=immediato)
#define AIR_THRESHOLD      10000.0f   // [ppm CO2]  — limite OSHA breve esposizione

// SO2 in ppb (parti per miliardo): unita' richiesta dal server cloud.
// Soglia WHO per esposizione 8h: 35 ppb.
// Il valore SO2 e' generato casualmente correlato con CO2:
// se CO2 supera soglia hardware (pin D7 HIGH), SO2 supera questa soglia.
#define SO2_THRESHOLD         35.0f   // [ppb SO2]  — soglia WHO 8h esposizione

#endif  // Fine guardia di inclusione CONFIG_H