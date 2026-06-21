//11 6 2026
#ifndef SENSORS_H
#define SENSORS_H

#include <DHT.h>
#include <time.h>
#include <Wire.h>
#include <Adafruit_MPU6050.h>
#include <Adafruit_Sensor.h>
#include "Config.h"

String getTimestamp();

/************ BASE CLASS ************/
class Sensor {
protected:
  String id;
  String type;

public:
  Sensor(String _id, String _type) : id(_id), type(_type) {}

  virtual bool read(String &value, String &msg) = 0;

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
// Soglie da Config.h:
// < TEMP_WARNING_C  → OK       severity: none
// < TEMP_CRITICAL_C → ERROR    severity: warning
// > TEMP_CRITICAL_C → ERROR    severity: critical
class TempSensor : public Sensor {
private:
  DHT* dht;

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
    if (v > TEMP_CRITICAL_C) {
      msg = "CRITICAL: Temperature too high (" + String(v, 1) + " C)";
      return false;
    }
    if (v > TEMP_WARNING_C) {
      msg = "WARNING: Temperature elevated (" + String(v, 1) + " C)";
      return false;
    }
    msg = "Temperature acquired";
    return true;
  }

  String buildResponseSeverity(String value, String msg) {
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
// Converte ADC grezzo in ppm CO2 usando la curva caratteristica
// del datasheet MQ-135 e valori statistici MQUnifiedsensor.
//
// Modello circuitale: Rs = RL * (Vcc - Vout) / Vout
// Curva caratteristica: ppm = a * (Rs/R0)^b
//
// Incertezza stimata: ±15% (R0 da media statistica, non calibrazione individuale)
// L'allarme hardware (pin DO) e' indipendente dalla stima ppm.
class AirSensor : public Sensor {
private:
  int analogPin;
  int digitalPin;

  static constexpr float RL_KOHM  = 10.0f;
  static constexpr float VCC      = 3.3f;
  static constexpr float ADC_MAX  = 1023.0f;
  static constexpr float R0_KOHM  = 76.63f;
  static constexpr float CO2_A    = 116.6020682f;
  static constexpr float CO2_B    = -2.769034857f;

  float adcToPpm(int raw) {
    if (raw <= 0) return -1.0f;
    float voltage = (raw / ADC_MAX) * VCC;
    if (voltage <= 0.0f || voltage >= VCC) return -1.0f;
    float Rs    = RL_KOHM * (VCC - voltage) / voltage;
    float ratio = Rs / R0_KOHM;
    if (ratio <= 0.0f) return -1.0f;
    return CO2_A * pow(ratio, CO2_B);
  }

public:
  AirSensor(String id, int _analogPin, int _digitalPin)
    : Sensor(id, "sensor"), analogPin(_analogPin), digitalPin(_digitalPin) {
    pinMode(digitalPin, INPUT);
  }

  bool read(String &value, String &msg) override {
    int raw     = analogRead(analogPin);
    int doState = digitalRead(digitalPin);

    if (raw < AIR_WARMUP_THR) {
      value = "null";
      msg   = "Sensor warming up";
      return false;
    }

    float ppm = adcToPpm(raw);
    if (ppm < 0.0f) {
      value = "null";
      msg   = "Air quality read failure";
      return false;
    }

    char buf[16];
    dtostrf(ppm, 6, 2, buf);
    value = String(buf);

    if (doState == HIGH) {
      msg = "CRITICAL: Air quality anomaly detected (" + String(buf) + " ppm CO2)";
      return false;
    }

    msg = "Air quality acquired (" + String(buf) + " ppm CO2)";
    return true;
  }
};

/************ SEISMIC SENSOR (MPU-6050) ************/
// Calibrazione automatica al boot (CAL_SAMPLES letture).
// Misura il delta rispetto al baseline calibrato.
// Funziona in qualsiasi orientamento fisico.
class SeismicSensor : public Sensor {
private:
  Adafruit_MPU6050* mpu;
  bool  ready;

  float baseline      = -1.0f;
  float calSum        =  0.0f;
  int   calCount      =  0;
  static const int CAL_SAMPLES = 10;

  float lastMagnitude =  0.0f;
  int   stuckCount    =  0;
  static const int STUCK_MAX = 5;  // 5 letture identiche = bus bloccato (~25s)

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

    // Watchdog: se il valore e' identico per STUCK_MAX letture consecutive
    // il bus I2C e' bloccato — reinizializza l'MPU.
    if (abs(magnitude - lastMagnitude) < 0.001f) {
      stuckCount++;
    } else {
      stuckCount = 0;
    }
    lastMagnitude = magnitude;

    if (stuckCount >= STUCK_MAX) {
      Serial.println("[MPU] Valore bloccato rilevato, reinizializzazione...");
      stuckCount = 0;
      if (mpu->begin(0x68)) {
        mpu->setAccelerometerRange(MPU6050_RANGE_16_G);
        mpu->setGyroRange(MPU6050_RANGE_250_DEG);
        mpu->setFilterBandwidth(MPU6050_BAND_5_HZ);
        // Reset calibrazione per ricalcolare il baseline
        baseline  = -1.0f;
        calSum    =  0.0f;
        calCount  =  0;
        Serial.println("[MPU] Reinizializzato, ricalibrazione...");
      } else {
        ready = false;
        Serial.println("[MPU] Reinizializzazione fallita");
      }
      value = "null";
      msg   = "MPU-6050 restarting";
      return false;
    }

    if (calCount < CAL_SAMPLES) {
      calSum += magnitude;
      calCount++;
      value = "0.000";
      msg   = "Calibrating (" + String(calCount) +
              "/" + String(CAL_SAMPLES) + ")";
      return true;
    }

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