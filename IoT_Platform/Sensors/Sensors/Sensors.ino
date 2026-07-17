//17_07_2026

/*
 * SENSORS.INO — Ciclo di vita del nodo IoT
 * ==========================================
 * Gestisce inizializzazione hardware/rete, loop principale e MQTT.
 * La logica dei singoli sensori e' in Sensors.h.
 *
 * Ordine di init nel setup():
 *   pin -> hardware locale -> WiFi -> NTP -> sensori -> MQTT -> prima pub.
 * I sensori si istanziano DOPO WiFi: i loro ID includono il MAC WiFi.
 *
 * Loop (non bloccante):
 *   verifica MQTT -> timeout LED -> pubblicazione periodica (ogni 5s)
 */

#include <ESP8266WiFi.h>        // WiFi per NodeMCU ESP8266
#include <PubSubClient.h>      // Client MQTT per Arduino/ESP
#include <DHT.h>               // Driver sensore DHT11
#include <ArduinoJson.h>       // Parsing e serializzazione JSON
#include <Wire.h>              // Comunicazione I2C (per MPU-6050)
#include <Adafruit_MPU6050.h>  // Driver accelerometro MPU-6050
#include <Adafruit_Sensor.h>   // Libreria base Adafruit (richiesta da MPU6050)
#include <time.h>              // Funzioni standard C per NTP e timestamp
#include "Config.h"            // Parametri di configurazione (soglie, pin, IP, ecc.)
#include "Sensors.h"           // Classi dei sensori (TempSensor, AirSensor, ecc.)

// =============================================================
// COSTANTI DI RETE E CONFIGURAZIONE
// =============================================================
#define DHTTYPE DHT11  // Tipo di sensore DHT: DHT11 (non DHT22)

// Credenziali WiFi e indirizzo broker letti da Config.h
const char* ssid      = WIFI_SSID;      // SSID della rete WiFi
const char* pass      = WIFI_PASS;      // Password WiFi
const char* ntpServer = "pool.ntp.org"; // Server NTP pubblico per sincronizzazione UTC

const char* MQTT_HOST = MQTT_HOST_ADDR; // IP del broker Mosquitto (da Config.h)
const int   MQTT_PORT = MQTT_PORT_NUM;  // Porta MQTT, default 1883 (da Config.h)

// Topic MQTT usati dal nodo
const char* TOPIC_PUB_AUTO = "iot/sensors";     // Pubblicazione periodica (ogni 5s)
const char* TOPIC_PUB_CMD  = "iot/sensors/cmd"; // Risposta a cmd_01 on-demand
const char* TOPIC_SUB      = "iot/cmd";         // Ricezione comandi dal gateway

// Timing: converte le macro da Config.h in variabili unsigned long
unsigned long SEND_INTERVAL   = SEND_INTERVAL_MS;   // Intervallo pubblicazione [ms]
const unsigned long BUZZER_DURATION = BUZZER_DURATION_MS; // Durata LED acceso [ms]

// =============================================================
// OGGETTI GLOBALI
// =============================================================
WiFiClient       wifiClient;          // Client TCP per la connessione WiFi
PubSubClient     mqtt(wifiClient);    // Client MQTT basato sul WiFiClient
DHT              dht(PIN_DHT, DHTTYPE); // Oggetto DHT11 sul pin D4
Adafruit_MPU6050 mpuChip;             // Oggetto driver MPU-6050

// Puntatori ai sensori: creati dinamicamente nel setup() dopo il WiFi
// perche' i loro ID includono il MAC WiFi (disponibile solo dopo la connessione)
TempSensor*    temp;     // Sensore temperatura DHT11 (ID: "MAC-t1")
AirSensor*     air;      // Sensore CO2 MQ-135 (ID: "MAC-aq1")
AirSensor*     so2;      // Sensore SO2 MQ-135 (ID: "MAC-aq2", valore random in ppb)
SeismicSensor* seismic;  // Sensore sismico MPU-6050 (ID: "MAC-s1")
Buzzer*        buzzer;   // LED di allarme sul pin D3 (ID: "MAC-buzzer")

// Array polimorfico: publishOnTopic() itera su Sensor* senza conoscere i tipi specifici
Sensor* sensors[4];  // Array dei 4 sensori logici pubblicati periodicamente
int SENSOR_COUNT = 4; // Numero di sensori nell'array (usato nei cicli for)

unsigned long lastSend     = 0;    // Timestamp dell'ultima pubblicazione periodica [ms]
unsigned long buzzerOnTime = 0;    // Timestamp attivazione LED; 0 = LED spento
bool          mpuReady     = false; // false se MPU-6050 non trovato al boot (graceful degradation)

// =============================================================
// FUNZIONI DI UTILITA'
// =============================================================

// nodeID() costruisce l'identificatore univoco del nodo dal MAC WiFi.
// Il MAC IEEE e' garantito univoco per dispositivo: nessuna configurazione manuale.
// Esempio output: "A4CF12F5A331" (MAC senza i due punti separatori)
String nodeID() {
  String mac = WiFi.macAddress(); // Legge il MAC WiFi (es. "A4:CF:12:F5:A3:31")
  mac.replace(":", "");           // Rimuove i separatori ":" dal MAC
  return mac;                     // Restituisce il MAC pulito (es. "A4CF12F5A331")
}

// getTimestamp() restituisce il timestamp UTC in formato ISO-8601.
// Richiede che la sincronizzazione NTP sia avvenuta nel setup().
// Formato output: "2026-07-10T14:30:00Z"
// Dichiarata anche in Sensors.h perche' e' usata da buildResponse().
String getTimestamp() {
  time_t now = time(nullptr);     // Legge il tempo corrente (secondi dall'epoca Unix)
  struct tm *t = gmtime(&now);    // Converte in struct tm in UTC (non locale)
  char buf[25];                   // Buffer per la stringa formattata
  sprintf(buf, "%04d-%02d-%02dT%02d:%02d:%02dZ",  // Formato ISO-8601 UTC
          t->tm_year+1900,  // Anno (tm_year e' anni dal 1900)
          t->tm_mon+1,      // Mese (tm_mon e' 0-11, aggiungo 1)
          t->tm_mday,       // Giorno del mese
          t->tm_hour,       // Ora
          t->tm_min,        // Minuti
          t->tm_sec);       // Secondi
  return String(buf);             // Converte il buffer char[] in String Arduino
}

// findSensor() cerca un sensore nell'array sensors[] per ID univoco.
// Usata dal callback MQTT per il comando cmd_01 con lista sensori specifici.
// Restituisce nullptr se l'ID non e' presente nell'array.
Sensor* findSensor(String id) {
  for (int i = 0; i < SENSOR_COUNT; i++)     // Itera su tutti i sensori
    if (sensors[i]->getID() == id) return sensors[i]; // Trovato: restituisce il puntatore
  return nullptr;  // Non trovato: restituisce null pointer
}

// severityFromMsg() deriva il livello di severity dal contenuto del messaggio.
// Questo evita di duplicare la logica tra la classe sensore e il codice di pubblicazione.
//   ok = true  -> "none"     (lettura normale, nessun problema)
//   "CRITICAL..." -> "critical" (soglia superata, allarme)
//   ok = false, altro -> "error" (guasto hardware, sensore non disponibile)
String severityFromMsg(bool ok, String msg) {
  if (ok) return "none";                     // Lettura normale: nessuna severity
  if (msg.startsWith("CRITICAL")) return "critical"; // Messaggio CRITICAL: severity critica
  return "error";                            // Altro errore: severity error
}

// buildSensorJson() assembla il record JSON completo per un singolo sensore.
// Delega la costruzione del JSON a Sensor::buildResponse() per centralizzare il formato.
String buildSensorJson(Sensor* s, String value, String msg, bool ok) {
  String sev = severityFromMsg(ok, msg);     // Calcola la severity dal messaggio
  return s->buildResponse(ok, value, msg, sev); // Chiama buildResponse sulla classe base
}

// =============================================================
// PUBBLICAZIONE MQTT
// =============================================================

// publishOnTopic() legge i sensori richiesti e pubblica il JSON aggregato.
// sensors_list vuota = legge tutti e 4 i sensori (pubblicazione periodica).
// sensors_list con ID separati da virgola = legge solo quelli (cmd_01).
void publishOnTopic(const char* topic, String sensors_list) {
  String json = "{\"node\":\"" + nodeID() + "\",\"responses\":["; // Intestazione JSON con MAC nodo
  bool first = true;  // Flag per gestire le virgole tra i record nell'array JSON

  if (sensors_list.length() == 0) {
    // Modalita' normale: legge tutti i sensori nell'array in ordine
    for (int i = 0; i < SENSOR_COUNT; i++) {   // Itera su tutti e 4 i sensori
      String value, msg;                        // Variabili per il valore e il messaggio
      bool ok = sensors[i]->read(value, msg);  // Legge il sensore (chiamata polimorfica)
      if (!first) json += ",";                  // Aggiunge la virgola tra i record (non prima del primo)
      json += buildSensorJson(sensors[i], value, msg, ok); // Aggiunge il record JSON
      first = false;                            // Dopo il primo, tutti i successivi hanno la virgola
    }
  } else {
    // Modalita' selettiva: legge solo i sensori specificati per ID
    int start = 0;                              // Indice di inizio nella stringa sensors_list
    while (start < (int)sensors_list.length()) { // Continua finche' ci sono ID da processare
      int end = sensors_list.indexOf(',', start); // Cerca la prossima virgola separatrice
      if (end == -1) end = sensors_list.length(); // Se non c'e' virgola: e' l'ultimo ID
      String id = sensors_list.substring(start, end); // Estrae l'ID corrente
      id.trim();                               // Rimuove spazi iniziali/finali dall'ID
      start = end + 1;                         // Avanza al prossimo ID (dopo la virgola)

      if (!first) json += ",";                 // Aggiunge la virgola tra i record
      Sensor* s = findSensor(id);             // Cerca il sensore per ID nell'array
      if (s == nullptr) {
        // ID non trovato: inserisce un record di errore nel JSON
        json += "{\"status\":\"ERROR\",\"severity\":\"error\","
                "\"type\":\"sensor\",\"id\":\"" + id + "\","   // ID richiesto (non trovato)
                "\"value\":null,\"message\":\"Sensor not found\","
                "\"timestamp\":\"" + getTimestamp() + "\","    // Timestamp della risposta
                "\"threshold\":null}";                         // Nessuna soglia per errore
      } else {
        String value, msg;                     // Variabili per il valore e il messaggio
        bool ok = s->read(value, msg);         // Legge il sensore trovato
        json += buildSensorJson(s, value, msg, ok); // Aggiunge il record JSON
      }
      first = false;                           // Dopo il primo record, aggiungi virgole
    }
  }

  json += "]}";                                // Chiude l'array responses e l'oggetto JSON
  Serial.println("[MQTT OUT] " + String(topic)); // Log del topic di pubblicazione
  Serial.println("[MQTT OUT] " + json);          // Log del payload completo
  mqtt.publish(topic, json.c_str());           // Pubblica il JSON sul topic MQTT
}

// =============================================================
// CALLBACK MQTT — Ricezione comandi dal gateway
// =============================================================
// Invocata automaticamente da mqtt.loop() quando arriva un messaggio su iot/cmd.
// Gestisce due comandi:
//   cmd_01 : lettura on-demand, risponde su iot/sensors/cmd
//   alarm  : accende (buzzer:1) o spegne (buzzer:0) il LED sul pin D3
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char p[length + 1];           // Buffer char per il payload (length+1 per il null terminator)
  memcpy(p, payload, length);   // Copia i byte del payload nel buffer
  p[length] = '\0';             // Aggiunge il null terminator per usarlo come stringa C

  Serial.println("\n[MQTT IN] topic=" + String(topic));  // Log del topic ricevuto
  Serial.println("[MQTT IN] payload=" + String(p));       // Log del payload

  StaticJsonDocument<512> doc;  // Documento JSON statico (512 byte, evita heap fragmentation)
  if (deserializeJson(doc, p)) { // Tenta il parsing del JSON
    Serial.println("[MQTT IN] JSON non valido"); // Parsing fallito: JSON malformato
    return;                       // Esce dalla callback senza processare
  }

  const char* cmd = doc["command"];  // Estrae il campo "command" dal JSON
  if (!cmd) return;                  // Se "command" e' assente: ignora il messaggio

  if (strcmp(cmd, "cmd_01") == 0) { // Comando di lettura on-demand
    JsonArray arr = doc["sensors"];  // Array opzionale di ID sensori da leggere
    String sensors_list = "";        // Stringa che accumulera' gli ID separati da virgola
    if (arr.size() > 0) {           // Se l'array e' presente e non vuoto:
      bool first = true;            // Flag per le virgole
      for (JsonVariant v : arr) {   // Itera su tutti gli ID nell'array JSON
        if (!first) sensors_list += ","; // Aggiunge la virgola tra gli ID
        sensors_list += v.as<String>();  // Aggiunge l'ID corrente alla lista
        first = false;
      }
    }
    // Pubblica su TOPIC_PUB_CMD (iot/sensors/cmd) invece di TOPIC_PUB_AUTO:
    // il gateway distingue le risposte ai comandi dai dati periodici automatici
    Serial.println("[CMD_01] Rispondo su " + String(TOPIC_PUB_CMD));
    publishOnTopic(TOPIC_PUB_CMD, sensors_list); // Pubblica la risposta
    return;                         // Comando gestito: esci dalla callback
  }

  if (strcmp(cmd, "alarm") == 0) { // Comando di controllo LED
    int val = doc["buzzer"] | 0;   // Legge il campo "buzzer" (0 o 1); default 0 se assente
    Serial.println("[CMD] Buzzer -> " + String(val ? "ON" : "OFF")); // Log azione
    buzzer->setState(val);         // Accende (1) o spegne (0) il LED sul pin D3
    if (val == 1) {
      buzzerOnTime = millis();     // Salva il timestamp di attivazione
      // Il loop() confrontera' millis()-buzzerOnTime con BUZZER_DURATION
      // e spegnera' il LED automaticamente alla scadenza
      Serial.println("[BUZZER] Si spegnera' in " +
                     String(BUZZER_DURATION / 1000) + "s"); // Log timeout
    } else {
      buzzerOnTime = 0;            // 0 = nessun timer attivo (LED spento manualmente)
      Serial.println("[BUZZER] Spento"); // Log spegnimento
    }
    return;                        // Comando gestito: esci dalla callback
  }

  if (strcmp(cmd, "mqtt_publication_interval") == 0) {
    unsigned long newInterval = doc["interval"] | SEND_INTERVAL_MS;
    String statusMsg = (newInterval >= 1000) ? "polling interval updated" : "error: interval too short";

    if (newInterval >= 1000) {
      SEND_INTERVAL = newInterval;
      Serial.println("[CMD] Intervallo aggiornato -> " + String(SEND_INTERVAL) + " ms");
    }

    // Costruisce un JSON minimale che rispetta la struttura attesa dal Gateway
    // Il gateway cerca l'array "responses", quindi dobbiamo mantenerlo
    String json = "{\"responses\":[{\"message\":\"" + statusMsg + "\"}]}";

    mqtt.publish(TOPIC_PUB_CMD, json.c_str());
    return;
  }

    // Pubblica la conferma sul topic dei comandi (lo stesso usato da cmd_01)
    mqtt.publish(TOPIC_PUB_CMD, json.c_str());
    return;
  }

  // Comando non riconosciuto: log di avviso
  Serial.println("[CMD] Comando sconosciuto: " + String(cmd));
}

// =============================================================
// CONNESSIONE MQTT
// =============================================================
// Tenta la connessione al broker con loop bloccante fino al successo.
// Chiamata sia dal setup() (prima connessione) che dal loop() (riconnessione).
void mqttConnect() {
  String clientId = "ESP-" + nodeID(); // Client ID univoco: "ESP-" + MAC (es. "ESP-A4CF12F5A331")
  while (!mqtt.connected()) {          // Ripete finche' la connessione non ha successo
    Serial.print("[MQTT] Connessione a " + String(MQTT_HOST) + "...");
    if (mqtt.connect(clientId.c_str())) { // Tenta la connessione al broker
      Serial.println(" OK");
      mqtt.subscribe(TOPIC_SUB);          // Si iscrive a iot/cmd per ricevere comandi
      Serial.println("[MQTT] Iscritto a " + String(TOPIC_SUB));
    } else {
      // Connessione fallita: stampa il codice di errore e riprova dopo 3 secondi
      Serial.println(" ERRORE rc=" + String(mqtt.state()) + " riprovo in 3s");
      delay(3000); // Attendi 3 secondi prima di ritentare
    }
  }
}

// Wrapper per la pubblicazione automatica di tutti i sensori sul topic periodico
void publishSensors() {
  publishOnTopic(TOPIC_PUB_AUTO, ""); // sensors_list vuota = pubblica tutti
}

// =============================================================
// SETUP — Inizializzazione all'avvio
// =============================================================
// L'ordine e' vincolato dalle dipendenze tra componenti:
//   1. Pin: D3 a LOW subito (evita LED accidentalmente acceso al boot)
//   2. Hardware: DHT11, I2C, MPU-6050 (graceful degradation se assente)
//   3. WiFi: loop bloccante (necessario prima di NTP e sensori)
//   4. NTP: timestamp UTC necessari nei record JSON del cloud
//   5. Sensori: istanziati dopo WiFi perche' ID include il MAC
//   6. MQTT: buffer 1280 byte (payload JSON ~700-800 byte > default 256)
//   7. Prima pubblicazione immediata: segnala al gateway che il nodo e' online
void setup() {
  Serial.begin(115200);    // Inizializza la porta seriale a 115200 baud per il debug
  delay(1000);             // Attendi 1 secondo per la stabilizzazione della seriale
  Serial.println("\n========== BOOT ==========");
  Serial.println("[CFG] IP broker: " + String(MQTT_HOST)); // Log IP broker
  Serial.println("[CFG] WiFi:      " + String(WIFI_SSID)); // Log SSID

  // Configura il pin LED come uscita e lo porta subito a LOW.
  // Alla prima accensione i GPIO dell'ESP8266 possono avere stato indeterminato:
  // senza questo LOW esplicito il LED potrebbe accendersi accidentalmente al boot.
  pinMode(PIN_BUZZER,   OUTPUT);         // D3 come uscita digitale
  digitalWrite(PIN_BUZZER, LOW);        // Porta D3 a LOW (LED spento)
  Serial.println("[BUZZER] Inizializzato a LOW");

  pinMode(PIN_MQ135_DO, INPUT);  // D7 come ingresso (comparatore MQ-135)
  pinMode(PIN_MPU_INT,  INPUT);  // D5 come ingresso (interrupt MPU, non usato)

  // Inizializza il seed del generatore random con micros():
  // micros() varia ad ogni avvio, quindi SO2 non ripete mai la stessa sequenza
  randomSeed(micros());          // seed da micros(): diverso ad ogni avvio
  dht.begin();                   // Inizializza il sensore DHT11
  Serial.println("[DHT] Inizializzato");

  Wire.begin();   // Avvia il bus I2C su pin predefiniti (SDA=D2, SCL=D1)
  delay(500);     // Attendi 500ms per la stabilizzazione delle linee I2C
  Serial.println("[MPU] Ricerca MPU-6050 su 0x68...");

  // Graceful degradation: se il chip non risponde, il nodo continua senza sismico.
  // Questo evita che un guasto hardware blocchi temperature e qualita' aria.
  if (!mpuChip.begin(0x68)) {  // Tenta init all'indirizzo I2C 0x68; restituisce false se fallisce
    Serial.println("[MPU] ERRORE: chip non trovato, continuo senza MPU");
    mpuReady = false;           // Flag: SeismicSensor restituira' "not available"
  } else {
    mpuReady = true;            // Chip trovato e inizializzato correttamente
    Serial.println("[MPU] MPU-6050 inizializzato");
    mpuChip.setAccelerometerRange(MPU6050_RANGE_16_G); // Range: +/-16g (massimo, piu' sensibile per sismi)
    mpuChip.setGyroRange(MPU6050_RANGE_250_DEG);       // Range giroscopio: +/-250 gradi/s
    mpuChip.setFilterBandwidth(MPU6050_BAND_5_HZ);    // Filtro digitale 5Hz: riduce rumore ADC
    Serial.println("[MPU] Range: 16G | Filter: 5Hz");
  }

  WiFi.begin(ssid, pass);  // Avvia la connessione WiFi con le credenziali di Config.h
  Serial.print("[WIFI] Connessione");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); } // Attende la connessione
  Serial.println("\n[WIFI] Connected");
  Serial.println("[IP]  " + WiFi.localIP().toString()); // Stampa l'IP assegnato dal DHCP
  Serial.println("[MAC] " + WiFi.macAddress());         // Stampa il MAC (usato per gli ID)

  // Sincronizzazione NTP: senza di essa i timestamp sarebbero riferiti
  // all'epoca Unix (1 gennaio 1970) e inutilizzabili per la correlazione
  // temporale nel database cloud.
  configTime(0, 0, ntpServer); // Configura NTP: offset UTC=0, daylight=0, server
  Serial.print("[NTP] Sincronizzazione");
  while (time(nullptr) < 100000) { delay(200); Serial.print("."); } // Attende sync (time > 100000 = valido)
  Serial.println("\n[NTP] Sincronizzato");

  // Istanziazione sensori: avviene DOPO WiFi perche' nodeID() usa il MAC.
  // aq1 e aq2 condividono gli stessi pin fisici (A0 e D7) ma usano
  // gas diversi (CO2 vs SO2) grazie al parametro AirGas.
  temp    = new TempSensor   (nodeID() + "-t1",     &dht);                            // DHT11
  air     = new AirSensor    (nodeID() + "-aq1",    PIN_MQ135_AO, PIN_MQ135_DO, AirGas::CO2); // MQ-135 CO2
  so2     = new AirSensor    (nodeID() + "-aq2",    PIN_MQ135_AO, PIN_MQ135_DO, AirGas::SO2); // MQ-135 SO2
  seismic = new SeismicSensor(nodeID() + "-s1",     &mpuChip, mpuReady);              // MPU-6050
  buzzer  = new Buzzer       (nodeID() + "-buzzer", PIN_BUZZER);                      // LED

  // Popola l'array polimorfico con i 4 sensori logici pubblicati periodicamente
  sensors[0] = temp;     // t1: temperatura
  sensors[1] = air;      // aq1: CO2
  sensors[2] = so2;      // aq2: SO2
  sensors[3] = seismic;  // s1: sismico

  Serial.println("[SENSORS] Inizializzati:");
  for (int i = 0; i < SENSOR_COUNT; i++)
    Serial.println("  - " + sensors[i]->getID()); // Stampa l'ID di ogni sensore

  // Configura e connette il client MQTT
  mqtt.setServer(MQTT_HOST, MQTT_PORT);  // Imposta indirizzo e porta del broker
  mqtt.setCallback(mqttCallback);        // Registra la funzione di callback per i messaggi in arrivo
  // Aumenta il buffer MQTT da 256 (default) a 1280 byte:
  // il payload JSON con 4 sensori raggiunge 700-800 byte, superando il default
  mqtt.setBufferSize(1280);
  mqttConnect();  // Prima connessione al broker (loop bloccante)

  // Assicura LED spento al boot (anche dopo un riavvio improvviso)
  buzzer->setState(0);  // Porta D3 a LOW (LED spento)
  buzzerOnTime = 0;     // Nessun timer attivo
  Serial.println("[BUZZER] Confermato OFF");

  Serial.println("[MQTT] Pronto");
  Serial.println("  Periodico -> " + String(TOPIC_PUB_AUTO)); // Log topic dati periodici
  Serial.println("  cmd_01    -> " + String(TOPIC_PUB_CMD));  // Log topic comandi
  Serial.println("=========================\n");

  // Prima pubblicazione immediata: segnala al gateway che il nodo e' online.
  // Senza di essa il gateway dovrebbe attendere fino a 5s per vedere il nodo.
  publishSensors();
  lastSend = millis(); // Inizializza il timer della pubblicazione periodica
}

// =============================================================
// LOOP — Ciclo principale (non bloccante)
// =============================================================
// Il loop deve essere rapido: mqtt.loop() va chiamato frequentemente
// per mantenere viva la connessione e ricevere messaggi dal gateway.
// Nessuna operazione bloccante deve essere inserita qui.
void loop() {
  // Verifica connessione MQTT ad ogni iterazione.
  // Se il broker si riavvia o la rete cade, riconnette automaticamente.
  if (!mqtt.connected()) mqttConnect(); // Riconnette se necessario (loop bloccante interno)
  mqtt.loop(); // Mantiene viva la connessione e invoca mqttCallback() se ci sono messaggi

  // Spegnimento automatico LED dopo BUZZER_DURATION millisecondi dall'attivazione.
  // Usa millis() invece di delay() per non bloccare il loop.
  // buzzerOnTime = 0 significa nessun timer attivo (LED gia' spento).
  if (buzzerOnTime > 0 && millis() - buzzerOnTime >= BUZZER_DURATION) {
    buzzer->setState(0);  // Spegne il LED portando D3 a LOW
    buzzerOnTime = 0;     // Resetta il timer
    Serial.println("[BUZZER] Disattivato automaticamente"); // Log spegnimento automatico
  }

  // Pubblicazione periodica ogni SEND_INTERVAL millisecondi (default: 5 secondi).
  // millis() restituisce il tempo in ms dall'ultimo boot: non si blocca mai.
  if (millis() - lastSend >= SEND_INTERVAL) { // Sono passati >= 5000ms dall'ultima pubblicazione?
    lastSend = millis();  // Aggiorna il timestamp dell'ultima pubblicazione
    publishSensors();     // Legge tutti i sensori e pubblica il JSON su iot/sensors
  }
}
