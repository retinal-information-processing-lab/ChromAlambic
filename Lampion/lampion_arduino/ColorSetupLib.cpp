#include "ColorSetupLib.h"
#include <SPI.h> 

// Defines for setting and clearing register bits
#ifndef cbi
#define cbi(sfr, bit) (_SFR_BYTE(sfr) &= ~_BV(bit))
#endif
#ifndef sbi
#define sbi(sfr, bit) (_SFR_BYTE(sfr) |= _BV(bit))
#endif

void initializeISR(byte timer2_compare_match) {
  noInterrupts();
  TCCR2A = 0;
  TCCR2B = 0;
  TCNT2 = 0;
  OCR2A = timer2_compare_match;
  bitSet(TCCR2B,CS21); // Prescaler 8
  bitSet(TIMSK2,OCIE2A);
  interrupts();
}

bool overclock = true;
void setupADC() {
  if (overclock) {
    sbi(ADCSRA,ADPS2) ;
    cbi(ADCSRA,ADPS1) ;
    cbi(ADCSRA,ADPS0) ;
  }
}

void setupSPI(int CS) {
  DIDR0 = 0x02; 
  SPI.begin(); 
  SPI.setDataMode(SPI_MODE0); 
  SPI.setClockDivider(SPI_CLOCK_DIV16); 
  pinMode(CS, OUTPUT);
  digitalWrite(CS, LOW); 
  SPI.transfer(0b00001000); 
  delay(1); SPI.transfer(0); delay(1); SPI.transfer(0); delay(1);
  SPI.transfer(0b00000001); 
  delay(1);
  digitalWrite(CS, HIGH); 
  digitalWrite(CS, LOW); 
  SPI.transfer(0b00000011); 
  delay(1);
  SPI.transfer(0b11110000); 
  delay(1); SPI.transfer(0); delay(1); SPI.transfer(0); delay(1);
  digitalWrite(CS, HIGH); 
}

bool triggerState(const int pin, float triggerThreshold){
  word ref = triggerThreshold*(1023/5) ;
  return (analogRead(pin) >= ref);
}

byte getLeftWord(word wavelength, float amplitude){
  amplitude/=2;
  word amplitudeBits = 4095/2.5*amplitude;
  byte address = 0;
  switch (wavelength){
    case 625: address=0b00000000; break;
    case 530: address=0b00010000; break;
    case 490: address=0b01010000; break;
    case 415: address=0b00110000; break;
    case 385: address=0b01000000; break;
  }
  return highByte(amplitudeBits) | address;
}

byte getRightWord(float amplitude){
  amplitude/=2;
  word amplitudeBits = 4095/2.5*amplitude;
  return lowByte(amplitudeBits);
}

void playColor(word wavelength, float amplitude, int CS) {
  byte leftWord = getLeftWord(wavelength, amplitude);
  byte rightWord = getRightWord(amplitude);
  
  digitalWrite(CS, LOW); 
  SPI.transfer(0b00000011);
  SPI.transfer(leftWord);
  SPI.transfer(rightWord);
  SPI.transfer(0);
  digitalWrite(CS, HIGH); 
}

void allOff(int CS) {
  digitalWrite(CS, LOW); 
  SPI.transfer(0b00000011);
  SPI.transfer(0b11110000);
  SPI.transfer(0b00000000);
  SPI.transfer(0);
  digitalWrite(CS, HIGH); 
}

bool checkStimOver(long lastTriggerTime, long offTime) {
  return ((millis()-lastTriggerTime>=offTime)&&(lastTriggerTime!=0));
}

// --- LA FONCTION CORRIGÉE POUR LE MODE MANUEL ---
// Elle utilise maintenant la même logique SPI (4 octets) que setupSPI/playColor
// mais accepte directement la valeur brute (0-4095) venant de Python.
void applyRawToDAC(int wavelength, uint16_t rawValue, int CS) {
    // 1. Calcul de l'adresse selon la longueur d'onde
    byte address = 0;
    switch (wavelength){
        case 625: address=0b00000000; break;
        case 530: address=0b00010000; break;
        case 490: address=0b01010000; break;
        case 420: // (Note: ton python dit 420, le .ino dit 415, j'ai mis les cas probables)
        case 415: address=0b00110000; break;
        case 385: address=0b01000000; break;
        default: return; // Sécurité
    }

    // 2. Préparation des octets de données
    byte leftWord = highByte(rawValue) | address;
    byte rightWord = lowByte(rawValue);

    // 3. Envoi SPI (Protocole 4 octets strict)
    digitalWrite(CS, LOW);
    SPI.transfer(0b00000011); // Commande d'écriture ?
    SPI.transfer(leftWord);   // Adresse + MSB
    SPI.transfer(rightWord);  // LSB
    SPI.transfer(0);          // Padding
    digitalWrite(CS, HIGH);
}