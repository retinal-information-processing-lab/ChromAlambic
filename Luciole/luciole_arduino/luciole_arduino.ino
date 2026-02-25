#include <SPI.h>
#include "ColorSetupLib.h"

// =============================================================================
// TUNABLE PARAMETERS
// =============================================================================
#define BUFFER_SIZE        100   // Number of mix slots in the circular buffer
#define REFILL_THRESHOLD   20    // Send refill request after this many mixes consumed
#define FREQ_N_TRIGGERS    10    // Number of trigger intervals used to estimate freq
#define TRIGGER_TOLERANCE  0.50f // +-50% of expected period triggers an error

// =============================================================================
// MESSAGE TYPE BYTES  (Arduino -> Python)
// =============================================================================
#define MSG_REFILL   0x01   // 0x01 + 1 byte  : number of mixes to send
#define MSG_FREQ     0x02   // 0x02 + 2 bytes : detected frequency (uint16, Hz)
#define MSG_TRIG_ERR 0x03   // 0x03 + 4 bytes : actual delta (uint32, microseconds)

// =============================================================================
// HARDWARE
// =============================================================================
const int   triggerPin           = A2;
#define     CS                     10
const int   timer2_compare_match = 79;
const float triggerThreshold     = 2.3f;
const long  offTime              = 1000; // ms silence -> allOff

// =============================================================================
// LED / CHANNEL CONFIG
// CONTRACT: activeWavelengths[] is always in ascending wavelength order,
//           matching the CSV column order (col0 = lowest wavelength).
// =============================================================================
#define MAX_CHANNELS 5
uint16_t activeWavelengths[MAX_CHANNELS];
byte     numActiveLeds = 0;

// =============================================================================
// CIRCULAR MIX BUFFER
// Stores raw 12-bit DAC values (0-4095) per active LED per mix slot.
// CONTRACT: mixBuffer[slot][i] -> activeWavelengths[i] (ascending wavelength)
//
// Sentinel design: FULL=(head+1)%SIZE==tail, EMPTY=head==tail
// Max usable slots = BUFFER_SIZE - 1 = 99
// =============================================================================
uint16_t mixBuffer[BUFFER_SIZE][MAX_CHANNELS];
volatile int bufHead = 0;
volatile int bufTail = 0;

inline int  bufNext(int idx) { return (idx + 1) % BUFFER_SIZE; }
inline bool bufFull()        { return bufNext(bufHead) == bufTail; }
inline bool bufEmpty()       { return bufHead == bufTail; }

// =============================================================================
// TRIGGER STATE
// =============================================================================
volatile short trigger_flag = 0;
short          flag_holder  = 0;
bool val = false, old_val = false;

unsigned long lastTriggerTime_ms = 0;
unsigned long lastTriggerTime_us = 0;

// =============================================================================
// FREQUENCY ESTIMATION
// =============================================================================
unsigned long freqIntervals[FREQ_N_TRIGGERS];
byte          freqSampleCount   = 0;
bool          freqDetected      = false;
unsigned long expectedPeriod_us = 0;

// =============================================================================
// REFILL TRACKING
// =============================================================================
byte consumedSinceRefill = 0;

// =============================================================================
// FORWARD DECLARATIONS
// =============================================================================
void handleSetup();
void receiveMixes();
void onTrigger();
void estimateAndSendFreq();
void sendTriggerError(unsigned long delta_us);

// =============================================================================
// SETUP
// =============================================================================
void setup() {
    Serial.begin(115200);
    setupSPI(CS);
    setupADC();
    initializeISR(timer2_compare_match);
    allOff(CS);

    // Block until Python sends the 'S' setup packet
    while (true) {
        if (Serial.available() > 0 && Serial.peek() == 'S') {
            handleSetup();
            break;
        }
    }
}

// =============================================================================
// MAIN LOOP
// =============================================================================
void loop() {
    // 1. Fill buffer from incoming Serial data
    receiveMixes();

    // 2. Handle trigger flags raised by ISR
    noInterrupts();
    flag_holder = trigger_flag;
    if (trigger_flag > 0) trigger_flag--;
    interrupts();

    if (flag_holder > 0) {
        unsigned long now_us = micros();
        lastTriggerTime_ms = millis();

        if (lastTriggerTime_us != 0) {
            unsigned long delta = now_us - lastTriggerTime_us;

            if (!freqDetected) {
                freqIntervals[freqSampleCount++] = delta;
                if (freqSampleCount >= FREQ_N_TRIGGERS) {
                    estimateAndSendFreq();
                }
            } else {
                unsigned long tol = (unsigned long)(expectedPeriod_us * TRIGGER_TOLERANCE);
                if (delta < expectedPeriod_us - tol || delta > expectedPeriod_us + tol) {
                    sendTriggerError(delta);
                }
            }
        }

        lastTriggerTime_us = now_us;
        onTrigger();
    }

    // 3. Safety: cut LEDs if DMD has gone silent
    if (lastTriggerTime_ms != 0 &&
        (millis() - lastTriggerTime_ms) > (unsigned long)offTime) {
        allOff(CS);
        lastTriggerTime_ms = 0;
    }
}

// =============================================================================
// onTrigger
// =============================================================================
void onTrigger() {
    if (bufEmpty()) {
        // Buffer underrun: hold last LED state, do nothing
        return;
    }

    // CONTRACT: i order matches activeWavelengths[] (ascending wavelength = CSV col order)
    for (int i = 0; i < numActiveLeds; i++) {
        applyRawToDAC(activeWavelengths[i], mixBuffer[bufTail][i], CS);
    }
    bufTail = bufNext(bufTail);

    consumedSinceRefill++;
    if (consumedSinceRefill >= REFILL_THRESHOLD) {
        Serial.write(MSG_REFILL);
        Serial.write(consumedSinceRefill); // slots now free
        consumedSinceRefill = 0;
    }
}

// =============================================================================
// receiveMixes — non-blocking, drains Serial into circular buffer
// =============================================================================
void receiveMixes() {
    int bytesPerMix = numActiveLeds * 2;
    if (bytesPerMix == 0) return;

    while (Serial.available() >= bytesPerMix && !bufFull()) {
        for (int i = 0; i < numActiveLeds; i++) {
            // CONTRACT: bytes arrive in ascending wavelength order (CSV col order)
            mixBuffer[bufHead][i] = ((uint16_t)Serial.read() << 8) |
                                     (uint16_t)Serial.read();
        }
        bufHead = bufNext(bufHead);
    }
}

// =============================================================================
// estimateAndSendFreq
// =============================================================================
void estimateAndSendFreq() {
    unsigned long sum = 0;
    for (byte i = 0; i < FREQ_N_TRIGGERS; i++) sum += freqIntervals[i];
    unsigned long avg_us = sum / FREQ_N_TRIGGERS;
    uint16_t hz = (uint16_t)((1000000UL + avg_us / 2UL) / avg_us);
    expectedPeriod_us = 1000000UL / (unsigned long)hz;
    freqDetected = true;

    Serial.write(MSG_FREQ);
    Serial.write((byte)((hz >> 8) & 0xFF));
    Serial.write((byte)( hz       & 0xFF));
}

// =============================================================================
// sendTriggerError
// =============================================================================
void sendTriggerError(unsigned long delta_us) {
    Serial.write(MSG_TRIG_ERR);
    Serial.write((byte)((delta_us >> 24) & 0xFF));
    Serial.write((byte)((delta_us >> 16) & 0xFF));
    Serial.write((byte)((delta_us >>  8) & 0xFF));
    Serial.write((byte)( delta_us        & 0xFF));
}

// =============================================================================
// handleSetup
//
// Packet format from Python:
//   'S'   (1 byte)
//   mask  (1 byte) bit0=385nm, bit1=420nm, bit2=490nm, bit3=530nm, bit4=625nm
//   (BUFFER_SIZE-1) mixes x numActiveLeds x 2 bytes (big-endian uint16)
//
// Responds with 'R' when armed.
// =============================================================================
void handleSetup() {
    Serial.read(); // consume 'S'

    while (Serial.available() < 1);
    byte mask = Serial.read();

    // Build activeWavelengths in ascending order
    // CONTRACT: bit order must match Python's mask-building order
    numActiveLeds = 0;
    const uint16_t wl_options[] = {385, 420, 490, 530, 625};
    for (int i = 0; i < 5; i++) {
        if ((mask >> i) & 1) {
            activeWavelengths[numActiveLeds] = wl_options[i];
            numActiveLeds++;
        }
    }

    // Reset all state
    bufHead = 0;
    bufTail = 0;
    trigger_flag        = 0;
    flag_holder         = 0;
    lastTriggerTime_ms  = 0;
    lastTriggerTime_us  = 0;
    freqSampleCount     = 0;
    freqDetected        = false;
    expectedPeriod_us   = 0;
    consumedSinceRefill = 0;
    val     = false;
    old_val = false;

    // Initial buffer fill: BUFFER_SIZE-1 mixes (sentinel slot stays empty)
    int initialFill = BUFFER_SIZE - 1;
    for (int slot = 0; slot < initialFill; slot++) {
        for (int i = 0; i < numActiveLeds; i++) {
            while (Serial.available() < 2);
            // CONTRACT: column order = ascending wavelength = CSV column order
            mixBuffer[slot][i] = ((uint16_t)Serial.read() << 8) |
                                  (uint16_t)Serial.read();
        }
    }
    bufHead = initialFill; // head=99, tail=0 -> 99 mixes ready

    Serial.write('R');
}

// =============================================================================
// ISR — Timer2, samples trigger pin at ~40kHz for edge detection
// =============================================================================
ISR(TIMER2_COMPA_vect) {
    TCNT2 = 0;
    old_val = val;
    val = triggerState(triggerPin, triggerThreshold);
    if (val == true && old_val == false) {
        trigger_flag++;
    }
}
