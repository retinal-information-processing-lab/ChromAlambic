#include <SPI.h>
#include "ColorSetupLib.h" 

// --- Configuration Hardware ---
const int triggerPin = A2;
#define CS 10
const int timer2_compare_match = 79; // Pour l'ISR (comme ton ref)
const float triggerThreshold = 2.3;
const long offTime = 1000; // Timeout de sécurité (ms)

// --- Paramètres de Mémoire ---
#define MAX_MIXES 150  
#define MAX_CHANNELS 5 

// --- Variables Globales ---
uint16_t lookupTable[MAX_MIXES][MAX_CHANNELS]; 
uint16_t activeWavelengths[MAX_CHANNELS];
byte numActiveLeds = 0;
int totalMixes = 0;

// Buffer circulaire
#define BUFFER_SIZE 128
volatile byte indexBuffer[BUFFER_SIZE];
volatile int head = 0;
volatile int tail = 0;

// Variables pour l'ISR (Interruption)
volatile short trigger_flag = 0;
short flag_holder = 0;
bool val = false, old_val = false;
unsigned long lastTriggerTime = 0;

void setup() {
    Serial.begin(115200); 
    setupSPI(CS);         
    setupADC();    
    // On initialise l'ISR sur le Timer2 pour une détection ultra-précise
    initializeISR(timer2_compare_match);     
    
    allOff(CS);           
}

void loop() {
    // 1. Réception Série (Remplissage du Buffer)
    if (Serial.available() > 0) {
        char cmd = Serial.peek(); 
        if (cmd == 'S') { 
            handleSetup(); 
        } else {
            byte idx = Serial.read();
            int nextHead = (head + 1) % BUFFER_SIZE;
            if (nextHead != tail) {
                indexBuffer[head] = idx;
                head = nextHead;
            }
        }
    }

    // 2. Traitement du Trigger (Via flag levé par l'ISR)
    noInterrupts();
    flag_holder = trigger_flag;
    if (trigger_flag > 0) trigger_flag--; // On décrémente un coup
    interrupts();

    if (flag_holder > 0) {
        lastTriggerTime = millis();
        onTrigger();
    }

    // 3. Sécurité : Timeout (Si le DMD s'arrête, on coupe tout)
    if (millis() - lastTriggerTime > offTime && lastTriggerTime != 0) {
        allOff(CS);
        lastTriggerTime = 0; // Reset pour ne pas spammer allOff
        // Optionnel : Envoyer un message d'erreur à Python si besoin
    }
}

// Fonction appelée quand un Trigger est validé par l'ISR
void onTrigger() {
    if (head != tail) {
        byte mixIdx = indexBuffer[tail];
        tail = (tail + 1) % BUFFER_SIZE;
        
        // Jouer la couleur
        for (int i = 0; i < numActiveLeds; i++) {
            applyRawToDAC(activeWavelengths[i], lookupTable[mixIdx][i], CS);
        }

        // ACK pour Python (Place libérée)
        Serial.write(0xA5); 
    }
}

// L'Interruption Service Routine (Le cœur de la détection)
ISR(TIMER2_COMPA_vect) {
  TCNT2 = 0;
  old_val = val;
  val = triggerState(triggerPin, triggerThreshold);
  // Front montant détecté
  if (val == true && old_val == false) {
    trigger_flag++;
  }
}

void handleSetup() {
    Serial.read(); // Consume 'S'
    while (Serial.available() < 2);
    byte mask = Serial.read(); 
    totalMixes = Serial.read(); 
    
    numActiveLeds = 0;
    uint16_t wl_options[] = {385, 420, 490, 530, 625};
    for(int i=0; i<5; i++) {
        if((mask >> i) & 1) {
            activeWavelengths[numActiveLeds] = wl_options[i];
            numActiveLeds++;
        }
    }

    for (int i = 0; i < totalMixes; i++) {
        for (int j = 0; j < numActiveLeds; j++) {
            while (Serial.available() < 2);
            lookupTable[i][j] = (Serial.read() << 8) | Serial.read();
        }
    }
    
    // Reset buffer et flags
    head = 0; 
    tail = 0;
    trigger_flag = 0;
    lastTriggerTime = 0;
    
    Serial.print('R'); // Handshake Ready
}