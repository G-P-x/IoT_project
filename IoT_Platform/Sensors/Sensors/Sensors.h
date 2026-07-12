//11_07_2026

/*
 * SENSORS.H — Definizione dei sensori e dell'attuatore
 * ======================================================
 * Contiene la gerarchia di classi che rappresenta tutti i dispositivi
 * fisici del nodo IoT. Ogni dispositivo estende la classe base astratta
 * Sensor, che impone un'interfaccia comune tramite read().
 *
 * Classi:
 *   Sensor        — classe base astratta
 *   TempSensor    — DHT11, temperatura in gradi C
 *   AirSensor     — MQ-135, CO2 (ppm) e SO2 (ppb random correlato CO2)
 *   SeismicSensor — MPU-6050, attivita' sismica via I2C
 *   Buzzer        — LED di allarme (ex buzzer piezoelettrico)
 */

#ifndef SENSORS_H   // Guardia di inclusione: evita doppia definizione
#define SENSORS_H

#include <DHT.h>                  // Libreria per sensore temperatura/umidita' DHT11
#include <time.h>                 // Funzioni standard C per gestione del tempo (timestamp)
#include <Wire.h>                 // Libreria Arduino per comunicazione I2C
#include <Adafruit_MPU6050.h>    // Driver per accelerometro/giroscopio MPU-6050
#include <Adafruit_Sensor.h>     // Libreria base Adafruit per sensori (richiesta da MPU6050)
#include "Config.h"              // Parametri di configurazione (soglie, pin, ecc.)

// Dichiarazione anticipata di getTimestamp(), definita in Sensors.ino.
// Restituisce il timestamp UTC corrente nel formato ISO-8601.
String getTimestamp();

// =============================================================
// CLASSE BASE: Sensor
// =============================================================
// Interfaccia comune a tutti i dispositivi fisici del nodo.
// L'array sensors[] in Sensors.ino contiene puntatori Sensor*:
// il codice di pubblicazione chiama read() polimorficamente su ciascuno
// senza conoscere il tipo specifico del sensore.
class Sensor {
protected:
  String id;    // Identificatore univoco (es. "A4CF12F5A331-t1")
  String type;  // "sensor" per sensori fisici, "actuator" per il LED

public:
  // Costruttore: inizializza id e type tramite lista di inizializzazione
  Sensor(String _id, String _type) : id(_id), type(_type) {}

  // read() e' il metodo principale da implementare in ogni sottoclasse.
  // Popola value (valore numerico come stringa) e msg (descrizione).
  // Restituisce true se la lettura e' normale, false se errore o CRITICAL.
  virtual bool  read(String &value, String &msg) = 0;  // = 0 = metodo puro (classe astratta)

  // getThreshold() espone la soglia critica del sensore.
  // Inclusa nel payload JSON cosi' il client sa quanto si e' superata la soglia.
  // Valore di default -1 significa "nessuna soglia" (es. per il LED).
  virtual float getThreshold() const { return -1.0f; }

  // buildResponse() assembla il record JSON nel formato atteso dal gateway:
  // {"status", "severity", "type", "id", "value", "message", "timestamp", "threshold"}
  String buildResponse(bool ok, String value, String msg,
                       String severity = "none") {
    float  thr    = getThreshold();                       // Legge la soglia del sensore
    String thrStr = (value == "null" || thr < 0.0f)      // threshold e' null se:
                    ? "null"                              //   - valore e' null (errore hardware)
                    : String(thr, 1);                     //   - sensore non ha soglia (thr < 0)

    return "{"                                                        // Apre il JSON
      "\"status\":\""    + String(ok ? "OK" : "ERROR") + "\","       // OK se lettura valida
      "\"severity\":\""  + severity                   + "\","        // none/error/critical
      "\"type\":\""      + type                       + "\","        // sensor o actuator
      "\"id\":\""        + id                         + "\","        // ID univoco del sensore
      "\"value\":"       + value                      + ","          // Valore numerico
      "\"message\":\""   + msg                        + "\","        // Messaggio descrittivo
      "\"timestamp\":\"" + getTimestamp()             + "\","        // Timestamp UTC ISO-8601
      "\"threshold\":"   + thrStr                     + "}";         // Soglia critica
  }

  String getID() { return id; }  // Getter per l'ID: usato da findSensor() in Sensors.ino
};

// =============================================================
// CLASSE: TempSensor — Sensore di temperatura DHT11
// =============================================================
// DHT11 su pin D4, protocollo single-wire proprietario.
// Precisione: +/-2°C. Restituisce NaN in caso di lettura fallita.
//
// Meccanismo failCount:
//   Conta le letture NaN consecutive. Dopo FAIL_THRESHOLD errori
//   reinizializza il sensore via dht->begin() senza bloccare gli altri.
class TempSensor : public Sensor {  // Eredita da Sensor
private:
  DHT* dht;  // Puntatore all'oggetto DHT creato in Sensors.ino

  int failCount = 0;                    // Contatore errori NaN consecutivi
  static const int FAIL_THRESHOLD = 5; // Dopo 5 errori: reinit del sensore

public:
  // Costruttore: passa id e tipo "sensor" alla classe base
  TempSensor(String id, DHT* _dht) : Sensor(id, "sensor"), dht(_dht) {}

  // Espone la soglia temperatura definita in Config.h
  float getThreshold() const override { return TEMP_THRESHOLD; }

  bool read(String &value, String &msg) override {
    float v = dht->readTemperature();    // Legge la temperatura [°C]; NaN se errore
    if (isnan(v)) {                      // isnan() controlla se il valore e' Not-a-Number
      failCount++;                       // Incrementa contatore errori consecutivi
      if (failCount >= FAIL_THRESHOLD) { // Se raggiunti 5 errori consecutivi:
        dht->begin();                    //   Reinizializza il sensore DHT11
        failCount = 0;                   //   Azzera il contatore dopo il reinit
        Serial.println("[DHT] Reinizializzato dopo " + String(FAIL_THRESHOLD) +
                       " errori consecutivi");  // Log del reinit
      }
      value = "null";                    // Pubblica null durante l'errore
      msg   = "Temperature read failure"; // Messaggio di errore per il gateway
      return false;                      // false = status ERROR nel JSON
    }
    failCount = 0;                       // Lettura valida: azzera contatore errori
    value = String(v, 1);               // Converte float in stringa con 1 decimale
    if (v > TEMP_THRESHOLD) {           // Supera la soglia critica?
      msg = "CRITICAL: Temperature too high (" + String(v, 1) + " C)"; // Messaggio CRITICAL
      return false;                      // false = status ERROR, severity critical
    }
    msg = "Temperature acquired";        // Lettura normale: messaggio informativo
    return true;                         // true = status OK nel JSON
  }
};

// =============================================================
// CLASSE: AirSensor — Sensore qualita' aria MQ-135
// =============================================================
// Lo stesso chip fisico genera due sensori logici distinti:
//   aq1 (AirGas::CO2): concentrazione CO2 in ppm, formula Rs/R0
//   aq2 (AirGas::SO2): valore SO2 in ppb, generato randomicamente
//                       correlato con il pin digitale D7 (comparatore CO2)
//
// Conversione ADC -> ppm (CO2):
//   Rs  = RL * (VCC - Vadc) / Vadc    resistenza sensore
//   ppm = A * (Rs/R0)^B               legge di potenza (curva datasheet)
//
// R0 = 7.2 kOhm calibrata in aria pulita a 3.3V (non 5V come nei datasheet)
// RL = 10 kOhm e' il resistore fisico di carico sul modulo MQ-135
//
// Warmup: i primi 6 cicli (30s) pubblica null perche' il sensore
// non e' ancora a temperatura operativa.
enum class AirGas { CO2, SO2 };  // Enum per selezionare il tipo di gas

class AirSensor : public Sensor {
private:
  int    analogPin;   // Pin A0: tensione analogica proporzionale al gas
  int    digitalPin;  // Pin D7: comparatore hardware (HIGH = CO2 sopra soglia)
  AirGas gas;         // CO2 o SO2: seleziona formula e soglia

  int warmupCount = 0;              // Conta i cicli di preriscaldamento
  static const int WARMUP_CYCLES = 6; // 6 cicli x 5s = 30 secondi di warmup

  // Costanti fisiche del circuito MQ-135
  static constexpr float RL_KOHM = 10.0f;   // Resistore di carico sul modulo [kOhm]
  static constexpr float VCC     = 3.3f;    // Tensione alimentazione NodeMCU [V]
  static constexpr float ADC_MAX = 1023.0f; // Valore massimo ADC 10-bit
  static constexpr float R0_KOHM = 7.2f;    // Resistenza in aria pulita calibrata a 3.3V [kOhm]

  // Coefficienti curva CO2: ppm_CO2 = 116.60 * (Rs/R0)^(-2.77)
  static constexpr float CO2_A = 116.6020682f;   // Coefficiente A curva CO2
  static constexpr float CO2_B = -2.769034857f;  // Esponente B curva CO2

  // Coefficienti curva SO2 (da librerie terze parti, non dal datasheet ufficiale Hanwei)
  static constexpr float SO2_A = 40.9734843f;    // Coefficiente A curva SO2
  static constexpr float SO2_B = -3.265256011f;  // Esponente B curva SO2

  // adcToPpm() converte la lettura ADC grezza in concentrazione ppm
  // tramite la formula Rs/R0 e la legge di potenza del datasheet.
  // Restituisce -1.0f se il valore e' fuori range o il sensore e' saturo.
  float adcToPpm(int raw) {
    if (raw <= 0) return -1.0f;                       // ADC a 0: sensore scollegato
    float voltage = (raw / ADC_MAX) * VCC;            // Converte ADC in tensione [V]
    if (voltage <= 0.0f || voltage >= VCC) return -1.0f; // Saturazione: fuori range
    float Rs    = RL_KOHM * (VCC - voltage) / voltage;   // Calcola resistenza sensore [kOhm]
    float ratio = Rs / R0_KOHM;                           // Rapporto Rs/R0 (adimensionale)
    if (ratio <= 0.0f) return -1.0f;                  // Rapporto non valido
    if (ratio < 0.05f) return -1.0f;                  // Sensore saturo o cortocircuitato
    float a   = (gas == AirGas::CO2) ? CO2_A : SO2_A; // Seleziona coefficiente A per il gas
    float b   = (gas == AirGas::CO2) ? CO2_B : SO2_B; // Seleziona coefficiente B per il gas
    float ppm = a * pow(ratio, b);                     // Applica legge di potenza: ppm = A*(Rs/R0)^B
    if (ppm <= 0.0f || ppm > 50000.0f) return -1.0f; // Valore fisicamente impossibile
    return ppm;                                        // Restituisce concentrazione in ppm
  }

  // gasName() restituisce il nome del gas come stringa per i messaggi
  String gasName() const {
    return (gas == AirGas::CO2) ? "CO2" : "SO2"; // "CO2" o "SO2" in base al tipo
  }

public:
  // Costruttore: inizializza pin, tipo gas e imposta pin digitale come input
  AirSensor(String id, int _analogPin, int _digitalPin,
            AirGas _gas = AirGas::CO2)      // Default: CO2 se gas non specificato
    : Sensor(id, "sensor"),                 // Chiama costruttore base con tipo "sensor"
      analogPin(_analogPin),               // Salva il pin analogico (A0)
      digitalPin(_digitalPin),             // Salva il pin digitale (D7)
      gas(_gas)                            // Salva il tipo di gas
  {
    pinMode(digitalPin, INPUT);  // Configura D7 come ingresso digitale
  }

  // Restituisce la soglia appropriata in base al gas:
  // CO2 -> AIR_THRESHOLD (ppm), SO2 -> SO2_THRESHOLD (ppb)
  float getThreshold() const override {
    return (gas == AirGas::CO2) ? AIR_THRESHOLD : SO2_THRESHOLD;
  }

  bool read(String &value, String &msg) override {
    int raw = analogRead(analogPin);  // Legge il valore ADC grezzo (0-1023)

    // Fase di warmup: sensore non ancora a temperatura operativa
    if (warmupCount < WARMUP_CYCLES) {
      warmupCount++;                  // Incrementa contatore cicli warmup
      value = "null";                 // Pubblica null durante il riscaldamento
      msg   = gasName() + " warming up ("
              + String(warmupCount) + "/" + String(WARMUP_CYCLES) + ")"; // Es. "CO2 warming up (2/6)"
      return false;                   // false = status ERROR (dati non affidabili)
    }

    // ADC troppo basso: probabile disconnessione del sensore dal pin A0
    if (raw < 50) {
      value = "null";                 // Valore non disponibile
      msg   = gasName() + " ADC basso (raw=" + String(raw) + ", controlla cablaggio)"; // Avviso cablaggio
      return false;                   // false = status ERROR
    }

    float ppm = adcToPpm(raw);       // Converte ADC in concentrazione ppm
    if (ppm < 0.0f) {                // adcToPpm restituisce -1 se fuori range
      value = "null";                // Valore non disponibile
      msg   = gasName() + " sensor not calibrated or saturated (raw=" + String(raw) + ")";
      return false;                  // false = status ERROR
    }

    char buf[16];                    // Buffer per la formattazione del numero
    dtostrf(ppm, 6, 2, buf);        // Converte float in stringa con 2 decimali, larghezza 6
    value = String(buf);            // Imposta il valore da pubblicare

    if (gas == AirGas::CO2) {
      // CO2: controlla il pin digitale D7 (comparatore hardware del modulo MQ-135).
      // Il comparatore va HIGH quando la resistenza del sensore supera la soglia
      // impostata dal potenziometro sul modulo, indipendentemente dalla formula software.
      int doState = digitalRead(digitalPin);  // Legge l'uscita del comparatore hardware
      if (doState == HIGH) {                  // HIGH = CO2 sopra soglia hardware
        msg = "CRITICAL: Air quality anomaly detected ("
              + String(buf) + " ppm CO2)";   // Messaggio CRITICAL con valore
        return false;                         // false = status ERROR, severity critical
      }
      msg = "CO2 acquired (" + String(buf) + " ppm)"; // Lettura normale CO2
      return true;                            // true = status OK
    } else {
      // SO2: valore randomico in ppb correlato con CO2.
      // L'MQ-135 non ha curva SO2 ufficiale nel datasheet Hanwei,
      // quindi il valore e' simulato casualmente in ppb.
      // Correlazione realistica: CO2 e SO2 aumentano insieme negli eventi vulcanici.
      // Se pin DO e' HIGH (CO2 sopra soglia hardware): SO2 supera SO2_THRESHOLD.
      // Se pin DO e' LOW (CO2 normale): SO2 resta in range normale (0.5-30 ppb).
      bool co2High = (digitalRead(digitalPin) == HIGH); // Legge stato CO2 dal comparatore

      float so2Ppb;                           // Variabile per il valore SO2 generato
      if (co2High) {
        // Genera SO2 sopra soglia: range [SO2_THRESHOLD+5, SO2_THRESHOLD+465] ppb
        so2Ppb = SO2_THRESHOLD + 5.0f         // Base: 5 ppb sopra la soglia
                 + (float)(random(0, 460))    // Componente intera casuale [0, 460]
                 + (float)(random(0, 100)) / 100.0f; // Componente decimale casuale [0.00, 0.99]
      } else {
        // Genera SO2 normale: range [0.5, 30.0] ppb (aria tipica)
        so2Ppb = 0.5f + (float)(random(0, 295)) / 10.0f; // 0.5 + [0.0, 29.5] ppb
      }
      char buf2[16];                          // Buffer per formattazione SO2
      dtostrf(so2Ppb, 6, 2, buf2);           // Converte SO2 in stringa con 2 decimali
      value = String(buf2);                  // Imposta il valore SO2 da pubblicare
      if (so2Ppb > SO2_THRESHOLD) {          // Supera la soglia WHO (35 ppb)?
        msg = "CRITICAL: SO2 anomaly detected ("
              + String(buf2) + " ppb SO2)";  // Messaggio CRITICAL con valore
        return false;                         // false = status ERROR, severity critical
      }
      msg = "SO2 acquired (" + String(buf2) + " ppb)"; // Lettura normale SO2
      return true;                            // true = status OK
    }
  }
};

// =============================================================
// CLASSE: SeismicSensor — Accelerometro MPU-6050
// =============================================================
// MPU-6050 su bus I2C (SDA=D2, SCL=D1), indirizzo 0x68.
//
// Il valore pubblicato NON e' l'accelerazione assoluta ma lo scostamento
// dalla baseline calcolata nelle prime CAL_SAMPLES letture post-boot:
//   delta = | sqrt(ax^2 + ay^2 + az^2) - baseline |
// Questo rende il rilevamento indipendente dall'orientamento del nodo.
//
// Problema freeze I2C: disturbi meccanici/elettrici possono corrompere
// una transazione I2C, bloccando il registro dati del chip su un valore fisso.
// Lo stuck detector (stuckCount) rileva questa condizione e reinizializza il chip.
//
// Soglia adattiva per il reinit:
//   - 1 ciclo (5s) se il valore congelato e' sopra SEISMIC_THRESHOLD
//   - STUCK_MAX (5) cicli (25s) se il valore e' nella norma
class SeismicSensor : public Sensor {
private:
  Adafruit_MPU6050* mpu;  // Puntatore al driver MPU-6050
  bool  ready;            // false se il chip non e' stato trovato al boot

  // Calibrazione: baseline calcolata dalle prime CAL_SAMPLES letture
  float baseline = -1.0f;         // Valore di riferimento a riposo; -1 = non ancora calcolato
  float calSum   =  0.0f;         // Somma accumulata delle magnitudini durante la calibrazione
  int   calCount =  0;            // Numero di campioni raccolti finora
  static const int CAL_SAMPLES = 10;  // Campioni necessari per calcolare la baseline

  // Stuck detector: confronta la magnitudine corrente con la precedente
  float lastMagnitude = 0.0f;     // Magnitudine dell'ultima lettura (per confronto)
  int   stuckCount    = 0;        // Cicli consecutivi con stesso valore (possibile freeze)
  static const int STUCK_MAX = 5; // Soglia normale: 5 cicli identici = freeze confermato

  // Contatore letture sopra soglia (anti-rumore transitorio)
  int   criticalCount = 0;        // Letture consecutive sopra SEISMIC_THRESHOLD
  const int CRITICAL_MIN = SEISMIC_CRITICAL_MIN; // Soglia da Config.h (default: 1)

  // Gestione post-reinit: la prima lettura dopo un reinit e' inaffidabile
  int   postReinitSkip = 0;       // >0 = salta questa lettura (chip in stabilizzazione)

  // Contatore reinit consecutivi: troppi reinit = baseline non piu' valida
  int   reinitCount    = 0;                       // Reinit consecutivi senza lettura normale
  static const int REINIT_RECAL_THRESHOLD = 3;    // Dopo 3 reinit: ricalibra la baseline

public:
  // Costruttore: ready viene impostato in Sensors.ino in base al risultato di mpu->begin()
  SeismicSensor(String id, Adafruit_MPU6050* _mpu, bool _ready)
    : Sensor(id, "sensor"), mpu(_mpu), ready(_ready) {} // Passa "sensor" alla classe base

  // Espone la soglia sismica da Config.h
  float getThreshold() const override { return SEISMIC_THRESHOLD; }

  bool read(String &value, String &msg) override {

    // [Stato 1] Sensore fisicamente non disponibile (non trovato al boot)
    if (!ready) {
      value = "null";               // Nessun dato disponibile
      msg   = "MPU-6050 not available"; // Messaggio di errore hardware
      return false;                 // false = status ERROR
    }

    // [Stato 2] Stabilizzazione post-reinit: salta la prima lettura.
    // Il chip MPU-6050 impiega ~100ms per produrre dati stabili dopo un reinit.
    // criticalCount viene azzerato per evitare falsi CRITICAL durante la transizione.
    if (postReinitSkip > 0) {
      postReinitSkip--;             // Decrementa il contatore (torna a 0 dopo 1 ciclo)
      criticalCount = 0;            // Azzera contatore CRITICAL per evitare falsi allarmi
      value = "null";               // Nessun dato affidabile in questa fase
      msg   = "MPU-6050 stabilizing"; // Informa che il chip si sta stabilizzando
      return false;                 // false = status ERROR (dato non affidabile)
    }

    // [Stato 3] Lettura I2C: richiede accelerazione sui 3 assi al chip
    sensors_event_t accel, gyro, temp;     // Strutture dati per i valori del sensore
    mpu->getEvent(&accel, &gyro, &temp);  // Legge tutti i valori via I2C in una chiamata

    float ax = accel.acceleration.x;  // Accelerazione sull'asse X [m/s^2]
    float ay = accel.acceleration.y;  // Accelerazione sull'asse Y [m/s^2]
    float az = accel.acceleration.z;  // Accelerazione sull'asse Z [m/s^2]
    // Magnitudine del vettore accelerazione: scalare indipendente dall'orientamento
    float magnitude = sqrt(ax*ax + ay*ay + az*az); // |a| = sqrt(ax^2 + ay^2 + az^2) [m/s^2]

    // [Stato 4] Stuck detection: attivo solo dopo la calibrazione completata.
    // Confronta la magnitudine corrente con l'ultima: se identiche (diff < 0.001)
    // e il valore e' anomalo (sopra soglia), il bus I2C e' probabilmente congelato.
    if (calCount >= CAL_SAMPLES) {   // Controlla solo se la calibrazione e' completa
      float frozenDelta = (baseline >= 0.0f) ? abs(magnitude - baseline) : 0.0f; // Scostamento attuale
      if (abs(magnitude - lastMagnitude) < 0.001f && frozenDelta > SEISMIC_THRESHOLD) {
        stuckCount++;               // Stesso valore anomalo: possibile freeze
      } else {
        stuckCount = 0;             // Valore cambiato: sensore attivo, azzera contatore
      }
    }
    lastMagnitude = magnitude;      // Aggiorna l'ultima magnitudine per il prossimo confronto

    // [Stato 5] Reinit condizionale con soglia adattiva.
    // Se il freeze e' su un valore anomalo: intervieni subito (1 ciclo = 5s)
    //   per non mantenere a lungo un CRITICAL falso attivo.
    // Se il freeze e' su un valore normale: aspetta piu' (25s)
    //   perche' un sensore fermo produce valori quasi identici di natura.
    float frozenDelta2 = (baseline >= 0.0f) ? abs(magnitude - baseline) : 0.0f; // Ricalcola delta
    int   stuckThresh  = (frozenDelta2 > SEISMIC_THRESHOLD) ? 1 : STUCK_MAX; // Soglia adattiva

    if (stuckCount >= stuckThresh) {  // Soglia raggiunta: freeze confermato
      Serial.println("[MPU] Valore bloccato, reinizializzazione...");
      stuckCount    = 0;              // Azzera il contatore stuck
      criticalCount = 0;              // Azzera il contatore CRITICAL
      if (mpu->begin(0x68)) {         // Tenta il reinit del chip all'indirizzo I2C 0x68
        mpu->setAccelerometerRange(MPU6050_RANGE_16_G);  // Range accelerometro: +/-16g (massimo)
        mpu->setGyroRange(MPU6050_RANGE_250_DEG);        // Range giroscopio: +/-250 gradi/s
        mpu->setFilterBandwidth(MPU6050_BAND_5_HZ);     // Filtro digitale passa-basso: 5Hz
        delay(100);                   // Attendi 100ms per la stabilizzazione del chip
        postReinitSkip = 1;           // Salta la prossima lettura (chip ancora instabile)
        reinitCount++;                // Incrementa il contatore reinit consecutivi

        if (reinitCount >= REINIT_RECAL_THRESHOLD && baseline >= 0.0f) {
          // Troppi reinit consecutivi senza lettura normale:
          // il nodo potrebbe essere stato spostato fisicamente.
          // Invalida la baseline per forzare una ricalibrazione completa.
          baseline    = -1.0f;        // Invalida la baseline (-1 = non calcolata)
          calSum      = 0.0f;         // Azzera la somma di calibrazione
          calCount    = 0;            // Azzera il contatore campioni
          reinitCount = 0;            // Azzera il contatore reinit
          Serial.println("[MPU] Ricalibrazione forzata");
        } else if (baseline < 0.0f) {
          // Baseline non ancora calcolata: reinicia la calibrazione
          calSum   = 0.0f;            // Azzera somma
          calCount = 0;               // Azzera contatore
          Serial.println("[MPU] Reinizializzato, ricalibrazione...");
        } else {
          // Baseline valida: mantienila e continua con il valore di riferimento esistente
          Serial.println("[MPU] Reinizializzato, baseline mantenuto (" +
                         String(baseline, 3) + " m/s2), reinit #" +
                         String(reinitCount));  // Log con baseline e numero reinit
        }
      } else {
        // Il reinit e' fallito: chip probabilmente irrecuperabile
        ready = false;               // Disabilita definitivamente il sensore
        Serial.println("[MPU] Reinizializzazione fallita");
      }
      value = "null";               // Nessun dato valido durante il reinit
      msg   = "MPU-6050 restarting"; // Informa che il chip si sta riavviando
      return false;                 // false = status ERROR
    }

    // [Stato 6] Calibrazione: accumula le prime CAL_SAMPLES letture.
    // Il delta e' pubblicato come "0.000" durante questa fase
    // e nessun CRITICAL puo' scattare (criticalCount non viene incrementato).
    if (calCount < CAL_SAMPLES) {
      calSum += magnitude;          // Accumula la magnitudine per il calcolo della media
      calCount++;                   // Incrementa il contatore campioni raccolti
      value = "0.000";             // Pubblica 0 durante la calibrazione (nessun evento)
      msg   = "Calibrating (" + String(calCount) +
              "/" + String(CAL_SAMPLES) + ")"; // Es. "Calibrating (3/10)"
      return true;                  // true = status OK (dati attesi durante calibrazione)
    }

    // Fissa la baseline al termine della calibrazione
    if (baseline < 0.0f) {          // baseline = -1 significa che non e' ancora stata calcolata
      baseline = calSum / (float)CAL_SAMPLES; // Media delle prime 10 magnitudini
      Serial.println("[MPU] Baseline: " + String(baseline, 3) + " m/s2"); // Log baseline
    }

    // [Stato 7] Rilevamento: calcola lo scostamento dalla baseline
    float delta = abs(magnitude - baseline); // |magnitudine_corrente - baseline|

    char buf[20];                    // Buffer per la formattazione del delta
    dtostrf(delta, 6, 3, buf);      // Converte float in stringa con 3 decimali
    value = String(buf);            // Imposta il valore da pubblicare

    if (delta > SEISMIC_THRESHOLD) {    // Delta supera la soglia sismica?
      criticalCount++;                  // Incrementa contatore letture sopra soglia
      if (criticalCount >= CRITICAL_MIN) { // Raggiunto il minimo di letture consecutive?
        msg = "CRITICAL: Seismic anomaly detected ("
              + String(delta, 3) + " m/s2)"; // Messaggio CRITICAL con valore
        return false;                   // false = status ERROR, severity critical
      }
    } else {
      criticalCount = 0;               // Delta normale: azzera il contatore CRITICAL
      reinitCount   = 0;               // Lettura normale: azzera il contatore reinit
    }

    msg = "Seismic acquired";          // Lettura normale: messaggio informativo
    return true;                       // true = status OK
  }
};

// =============================================================
// CLASSE: Buzzer — LED di allarme (ex buzzer piezoelettrico)
// =============================================================
// Il buzzer originale e' stato sostituito con un LED per eliminare
// gli spike di corrente che causavano il freeze I2C durante gli eventi.
// Il LED e' attivato SOLO via comando MQTT remoto "alarm" dal gateway:
// non esiste attivazione automatica locale nel firmware del nodo.
//
// read() non e' usato per il LED (e' un attuatore, non un sensore),
// ma deve essere implementato per rispettare l'interfaccia Sensor astratta.
class Buzzer : public Sensor {
private:
  int pin;  // Pin digitale D3 collegato al LED tramite resistenza 220 Ohm
public:
  // Costruttore: passa tipo "actuator" alla classe base (non "sensor")
  Buzzer(String id, int _pin) : Sensor(id, "actuator"), pin(_pin) {}

  // read() obbligatorio per l'interfaccia ma non usato per il LED
  bool read(String &value, String &msg) override {
    value = "null";         // Il LED non restituisce valori misurabili
    msg   = "Not readable"; // Messaggio che indica che non e' un sensore
    return false;           // false = status ERROR (ma non genera allarme)
  }

  // setState() accende (val=1) o spegne (val=0) il LED.
  // Chiamato dal callback MQTT quando arriva il comando "alarm".
  String setState(int val) {
    digitalWrite(pin, val ? HIGH : LOW); // HIGH = LED acceso, LOW = LED spento
    return buildResponse(true, String(val),
      val ? "Buzzer activated" : "Buzzer disabled", "none"); // JSON di conferma
  }
};

#endif  // Fine guardia di inclusione SENSORS_H