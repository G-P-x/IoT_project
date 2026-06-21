#ifndef SENSORS_H
#define SENSORS_H

#include <DHT.h>
#include <time.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>

String getTimestamp();

/************ BASE CLASS ************/
class Sensor {
protected:
  String id;
  String type;

public:
  Sensor(String _id, String _type) : id(_id), type(_type) {}

  virtual bool read(String &value, String &msg) = 0;

  // severity: "none" | "warning" | "critical" | "error"
  String buildResponse(bool ok, String value, String msg,
                       String severity = "none") {
    return "{"
      "\"status\":\""    + String(ok ? "OK" : "ERROR") + "\","
      "\"severity\":\""  + severity + "\","
      "\"type\":\""      + type    + "\","
      "\"id\":\""        + id      + "\","
      "\"value\":"       + value   + ","
      "\"message\":\""   + msg     + "\","
      "\"timestamp\":\"" + getTimestamp() + "\""
    "}";
  }

  String getID() { return id; }
};

/************ TEMP SENSOR (DHT11) ************/
// Soglie:
// < 40°C  → OK       severity: none
// 40-60°C → ERROR    severity: warning  (caldo anomalo)
// > 60°C  → ERROR    severity: critical (pericolo)
class TempSensor : public Sensor {
private:
  DHT* dht;
  static constexpr float TEMP_WARNING  = 40.0f;
  static constexpr float TEMP_CRITICAL = 60.0f;

public:
  TempSensor(String id, DHT* _dht) : Sensor(id, "sensor"), dht(_dht) {}

  bool read(String &value, String &msg) override {
    float v = dht->readTemperature();
    if (isnan(v)) {
      value = "null";
      msg   = "Temperature read failure";
      return false;
    }
    value = String(v, 1);
    if (v > TEMP_CRITICAL) {
      msg = "CRITICAL: Temperature too high (" + String(v, 1) + " C)";
      return false;
    }
    if (v > TEMP_WARNING) {
      msg = "WARNING: Temperature elevated (" + String(v, 1) + " C)";
      return false;
    }
    msg = "Temperature acquired";
    return true;
  }

  // Costruisce la risposta con il severity corretto
  String buildResponseSeverity(String value, String msg) {
    float v = value.toFloat();
    if (msg.startsWith("CRITICAL"))
      return buildResponse(false, value, msg, "critical");
    if (msg.startsWith("WARNING"))
      return buildResponse(false, value, msg, "warning");
    if (msg == "Temperature read failure")
      return buildResponse(false, value, msg, "error");
    return buildResponse(true, value, msg, "none");
  }
};

/************ AIR SENSOR (MQ-135 / FC-22) ************/
// AO -> A0 : valore analogico grezzo 0-1023
// DO -> D7 : HIGH se la soglia hardware del trimmer e' superata
class AirSensor : public Sensor {
private:
  int analogPin;
  int digitalPin;
  static const int WARMUP_THRESHOLD = 50;

public:
  AirSensor(String id, int _analogPin, int _digitalPin)
    : Sensor(id, "sensor"), analogPin(_analogPin), digitalPin(_digitalPin) {
    pinMode(digitalPin, INPUT);
  }

  bool read(String &value, String &msg) override {
    int raw     = analogRead(analogPin);
    int doState = digitalRead(digitalPin);

    if (raw < WARMUP_THRESHOLD) {
      value = String(raw);
      msg   = "Sensor warming up";
      return false;
    }

    value = String(raw);

    if (doState == HIGH) {
      msg = "CRITICAL: Air quality anomaly detected (threshold exceeded)";
      return false;
    }

    msg = "Air quality acquired";
    return true;
  }
};

/************ SEISMIC SENSOR (MPU-6050) ************/
// Calibrazione automatica al boot (CAL_SAMPLES letture).
// Misura il delta rispetto al baseline calibrato.
// Cosi' funziona in qualsiasi orientamento fisico.
class SeismicSensor : public Sensor {
private:
  Adafruit_MPU6050* mpu;
  bool  ready;

  float baseline = -1.0f;
  float calSum   =  0.0f;
  int   calCount =  0;
  static const int CAL_SAMPLES = 10;

  static constexpr float SEISMIC_THRESHOLD = 2.0f;  // m/s²

public:
  SeismicSensor(String id, Adafruit_MPU6050* _mpu, bool _ready)
    : Sensor(id, "sensor"), mpu(_mpu), ready(_ready) {}

  bool read(String &value, String &msg) override {
    if (!ready) {
      value = "null";
      msg   = "MPU-6050 not available";
      return false;
    }

    sensors_event_t accel, gyro, temp;
    mpu->getEvent(&accel, &gyro, &temp);

    float ax = accel.acceleration.x;
    float ay = accel.acceleration.y;
    float az = accel.acceleration.z;
    float magnitude = sqrt(ax*ax + ay*ay + az*az);

    // Fase di calibrazione
    if (calCount < CAL_SAMPLES) {
      calSum += magnitude;
      calCount++;
      value = "0.000";
      msg   = "Calibrating (" + String(calCount) +
              "/" + String(CAL_SAMPLES) + ")";
      return true;
    }

    // Prima lettura post-calibrazione
    if (baseline < 0.0f) {
      baseline = calSum / (float)CAL_SAMPLES;
      Serial.println("[MPU] Baseline: " + String(baseline, 3) + " m/s2");
    }

    float delta = abs(magnitude - baseline);

    char buf[20];
    dtostrf(delta, 6, 3, buf);
    value = String(buf);

    if (delta > SEISMIC_THRESHOLD) {
      msg = "CRITICAL: Seismic anomaly detected (" + String(delta, 3) + " m/s2)";
      return false;
    }

    msg = "Seismic acquired";
    return true;
  }
};

/************ BUZZER ************/
class Buzzer : public Sensor {
private:
  int pin;
public:
  Buzzer(String id, int _pin) : Sensor(id, "actuator"), pin(_pin) {}

  bool read(String &value, String &msg) override {
    value = "null";
    msg   = "Not readable";
    return false;
  }

  String setState(int val) {
    digitalWrite(pin, val ? HIGH : LOW);
    return buildResponse(true, String(val),
      val ? "Buzzer activated" : "Buzzer disabled", "none");
  }
};

#endif