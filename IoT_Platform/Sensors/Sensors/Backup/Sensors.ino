//11 6 2026
#include <ESP8266WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include <time.h>
#include "Config.h"
#include "Sensors.h"

/************ PIN CONFIG (da Config.h) ************/
#define DHTTYPE DHT11

/************ NETWORK (da Config.h) ************/
const char* ssid      = WIFI_SSID;
const char* pass      = WIFI_PASS;
const char* ntpServer = "pool.ntp.org";

const char* MQTT_HOST = MQTT_HOST_ADDR;
const int   MQTT_PORT = MQTT_PORT_NUM;

const char* TOPIC_PUB_AUTO = "iot/sensors";
const char* TOPIC_PUB_CMD  = "iot/sensors/cmd";
const char* TOPIC_SUB      = "iot/cmd";

/************ TIMING (da Config.h) ************/
const unsigned long SEND_INTERVAL   = SEND_INTERVAL_MS;
const unsigned long BUZZER_DURATION = BUZZER_DURATION_MS;

/************ OBJECTS ************/
WiFiClient       wifiClient;
PubSubClient     mqtt(wifiClient);
DHT              dht(PIN_DHT, DHTTYPE);
Adafruit_MPU6050 mpuChip;

TempSensor*    temp;
AirSensor*     air;
SeismicSensor* seismic;
Buzzer*        buzzer;

Sensor* sensors[3];
int SENSOR_COUNT = 3;

unsigned long lastSend     = 0;
unsigned long buzzerOnTime = 0;
bool          mpuReady     = false;

/************ NODE ID ************/
String nodeID() {
  String mac = WiFi.macAddress();
  mac.replace(":", "");
  return mac;
}

/************ TIMESTAMP ************/
String getTimestamp() {
  time_t now = time(nullptr);
  struct tm *t = gmtime(&now);
  char buf[25];
  sprintf(buf, "%04d-%02d-%02dT%02d:%02d:%02dZ",
          t->tm_year+1900, t->tm_mon+1, t->tm_mday,
          t->tm_hour, t->tm_min, t->tm_sec);
  return String(buf);
}

/************ FIND SENSOR BY ID ************/
Sensor* findSensor(String id) {
  for (int i = 0; i < SENSOR_COUNT; i++)
    if (sensors[i]->getID() == id) return sensors[i];
  return nullptr;
}

/************ SEVERITY FROM MESSAGE ************/
String severityFromMsg(bool ok, String msg) {
  if (ok) return "none";
  if (msg.startsWith("CRITICAL")) return "critical";
  if (msg.startsWith("WARNING"))  return "warning";
  return "error";
}

/************ BUILD SENSOR JSON ************/
String buildSensorJson(int index, Sensor* s, String value, String msg, bool ok) {
  String sev = severityFromMsg(ok, msg);
  if (index == 0 || s->getID().endsWith("-t1"))
    return ((TempSensor*)s)->buildResponseSeverity(value, msg);
  return s->buildResponse(ok, value, msg, sev);
}

/************ PUBLISH ON TOPIC ************/
void publishOnTopic(const char* topic, String sensors_list) {
  // Le soglie vengono incluse solo nel topic periodico (non nelle risposte cmd_01)
  // cosi' il gateway conosce sempre i valori attivi sull'ESP.
  String thresholds = "";
  if (String(topic) == String(TOPIC_PUB_AUTO)) {
    thresholds = ",\"thresholds\":{"
      "\"temp_warning\":"     + String(TEMP_WARNING_C,    1) + ","
      "\"temp_critical\":"    + String(TEMP_CRITICAL_C,   1) + ","
      "\"seismic\":"          + String(SEISMIC_THRESHOLD, 1) + ","
      "\"air_warning_ppm\":" + String((int)AIR_WARNING_PPM)  + ","
      "\"air_critical_ppm\":" + String((int)AIR_CRITICAL_PPM) +
      "}";
  }

  String json = "{\"node\":\"" + nodeID() + "\"" + thresholds + ",\"responses\":[";
  bool first = true;

  if (sensors_list.length() == 0) {
    for (int i = 0; i < SENSOR_COUNT; i++) {
      String value, msg;
      bool ok = sensors[i]->read(value, msg);
      if (!first) json += ",";
      json += buildSensorJson(i, sensors[i], value, msg, ok);
      first = false;
    }
  } else {
    int start = 0;
    while (start < (int)sensors_list.length()) {
      int end = sensors_list.indexOf(',', start);
      if (end == -1) end = sensors_list.length();
      String id = sensors_list.substring(start, end);
      id.trim();
      start = end + 1;

      if (!first) json += ",";
      Sensor* s = findSensor(id);
      if (s == nullptr) {
        json += "{\"status\":\"ERROR\",\"severity\":\"error\","
                "\"type\":\"sensor\",\"id\":\"" + id + "\","
                "\"value\":null,\"message\":\"Sensor not found\","
                "\"timestamp\":\"" + getTimestamp() + "\"}";
      } else {
        String value, msg;
        bool ok = s->read(value, msg);
        String sev = severityFromMsg(ok, msg);
        if (id.endsWith("-t1"))
          json += ((TempSensor*)s)->buildResponseSeverity(value, msg);
        else
          json += s->buildResponse(ok, value, msg, sev);
      }
      first = false;
    }
  }

  json += "]}";
  Serial.println("[MQTT OUT] " + String(topic));
  Serial.println("[MQTT OUT] " + json);
  mqtt.publish(topic, json.c_str());
}

/************ MQTT CALLBACK ************/
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char p[length + 1];
  memcpy(p, payload, length);
  p[length] = '\0';

  Serial.println("\n[MQTT IN] topic=" + String(topic));
  Serial.println("[MQTT IN] payload=" + String(p));

  StaticJsonDocument<512> doc;
  if (deserializeJson(doc, p)) {
    Serial.println("[MQTT IN] JSON non valido");
    return;
  }

  const char* cmd = doc["command"];
  if (!cmd) return;

  if (strcmp(cmd, "cmd_01") == 0) {
    JsonArray arr = doc["sensors"];
    String sensors_list = "";
    if (arr.size() > 0) {
      bool first = true;
      for (JsonVariant v : arr) {
        if (!first) sensors_list += ",";
        sensors_list += v.as<String>();
        first = false;
      }
    }
    Serial.println("[CMD_01] Rispondo su " + String(TOPIC_PUB_CMD));
    publishOnTopic(TOPIC_PUB_CMD, sensors_list);
    return;
  }

  if (strcmp(cmd, "alarm") == 0) {
    int val = doc["buzzer"] | 0;
    Serial.println("[CMD] Buzzer -> " + String(val ? "ON" : "OFF"));
    buzzer->setState(val);
    if (val == 1) {
      buzzerOnTime = millis();
      Serial.println("[BUZZER] Si spegnera' in " +
                     String(BUZZER_DURATION / 1000) + "s");
    } else {
      buzzerOnTime = 0;
      Serial.println("[BUZZER] Spento");
    }
    return;
  }

  Serial.println("[CMD] Comando sconosciuto: " + String(cmd));
}

/************ MQTT CONNECT ************/
void mqttConnect() {
  String clientId = "ESP-" + nodeID();
  while (!mqtt.connected()) {
    Serial.print("[MQTT] Connessione a " + String(MQTT_HOST) + "...");
    if (mqtt.connect(clientId.c_str())) {
      Serial.println(" OK");
      mqtt.subscribe(TOPIC_SUB);
      Serial.println("[MQTT] Iscritto a " + String(TOPIC_SUB));
    } else {
      Serial.println(" ERRORE rc=" + String(mqtt.state()) + " riprovo in 3s");
      delay(3000);
    }
  }
}

/************ PUBLISH PERIODICO ************/
void publishSensors() {
  publishOnTopic(TOPIC_PUB_AUTO, "");
}

/************ SETUP ************/
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("\n========== BOOT ==========");
  Serial.println("[CFG] IP broker: " + String(MQTT_HOST));
  Serial.println("[CFG] WiFi:      " + String(WIFI_SSID));

  pinMode(PIN_BUZZER, OUTPUT);
  digitalWrite(PIN_BUZZER, LOW);
  Serial.println("[BUZZER] Inizializzato a LOW");

  pinMode(PIN_MQ135_DO, INPUT);
  pinMode(PIN_MPU_INT,  INPUT);

  dht.begin();
  Serial.println("[DHT] Inizializzato");

  Wire.begin();
  delay(500);
  Serial.println("[MPU] Ricerca MPU-6050 su 0x68...");

  if (!mpuChip.begin(0x68)) {
    Serial.println("[MPU] ERRORE: chip non trovato, continuo senza MPU");
    mpuReady = false;
  } else {
    mpuReady = true;
    Serial.println("[MPU] MPU-6050 inizializzato");
    mpuChip.setAccelerometerRange(MPU6050_RANGE_16_G);
    mpuChip.setGyroRange(MPU6050_RANGE_250_DEG);
    mpuChip.setFilterBandwidth(MPU6050_BAND_5_HZ);
    Serial.println("[MPU] Range: 16G | Filter: 5Hz");
  }

  WiFi.begin(ssid, pass);
  Serial.print("[WIFI] Connessione");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println("\n[WIFI] Connected");
  Serial.println("[IP]  " + WiFi.localIP().toString());
  Serial.println("[MAC] " + WiFi.macAddress());

  configTime(0, 0, ntpServer);
  Serial.print("[NTP] Sincronizzazione");
  while (time(nullptr) < 100000) { delay(200); Serial.print("."); }
  Serial.println("\n[NTP] Sincronizzato");

  temp    = new TempSensor(nodeID() + "-t1",     &dht);
  air     = new AirSensor(nodeID()  + "-aq1",    PIN_MQ135_AO, PIN_MQ135_DO);
  seismic = new SeismicSensor(nodeID() + "-s1",  &mpuChip, mpuReady);
  buzzer  = new Buzzer(nodeID()     + "-buzzer", PIN_BUZZER);

  sensors[0] = temp;
  sensors[1] = air;
  sensors[2] = seismic;

  Serial.println("[SENSORS] Inizializzati:");
  for (int i = 0; i < SENSOR_COUNT; i++)
    Serial.println("  - " + sensors[i]->getID());

  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(mqttCallback);
  mqtt.setBufferSize(1024);
  mqttConnect();

  buzzer->setState(0);
  buzzerOnTime = 0;
  Serial.println("[BUZZER] Confermato OFF");

  Serial.println("[MQTT] Pronto");
  Serial.println("  Periodico -> " + String(TOPIC_PUB_AUTO));
  Serial.println("  cmd_01    -> " + String(TOPIC_PUB_CMD));
  Serial.println("=========================\n");

  publishSensors();
  lastSend = millis();
}

/************ LOOP ************/
void loop() {
  if (!mqtt.connected()) mqttConnect();
  mqtt.loop();

  if (buzzerOnTime > 0 && millis() - buzzerOnTime >= BUZZER_DURATION) {
    buzzer->setState(0);
    buzzerOnTime = 0;
    Serial.println("[BUZZER] Disattivato automaticamente");
  }

  if (millis() - lastSend >= SEND_INTERVAL) {
    lastSend = millis();
    publishSensors();
  }
}
