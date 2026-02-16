#ifndef ColorSetupLib
#define ColorSetupLib

#include <Arduino.h>
#include <SPI.h>

// Interrupt Service Routine on Timer0
void initializeISR(byte timer2_compare_match);

// ADC setup
void setupADC();

// Trigger state measurement
bool triggerState(const int pin, float triggerThreshold);

// Setup SPI communication
void setupSPI(int CS);

// Get the left word (Legacy helper)
byte getLeftWord(word wavelength, float amplitude);

// Get the right word (Legacy helper)
byte getRightWord(float amplitude);

// Play a color (Voltage based)
void playColor(word wavelength, float amplitude, int CS);

// Turn all LEDs off
void allOff(int CS);

// Check if stimulation is over
bool checkStimOver(long lastTriggerTime, long offTime);

// --- NOUVELLE FONCTION CORRIGÉE ---
// Raw bits based (0-4095) for manual control
void applyRawToDAC(int wavelength, uint16_t rawValue, int CS);

#endif