#include <SPI.h>
#include "ColorSetupLib.h" 

#define CS 10 

void setup() {
    Serial.begin(115200);
    setupSPI(CS);         
    setupADC();         
    allOff(CS);           
}

void loop() {
    if (Serial.available() >= 4) {
        char cmd = Serial.read();
        if (cmd == 'D') { // Commande Directe de Lampion
            // Lecture des 3 octets suivants : Index, HighByte, LowByte
            byte ledIdx = Serial.read(); 
            byte high = Serial.read();   
            byte low = Serial.read();    
            uint16_t rawValue = (high << 8) | low;

            uint16_t wl_options[] = {385, 415, 490, 530, 625};
            
            if (ledIdx < 5) {
                // On appelle la fonction de la librairie (corrigée)
                // On passe le pin CS explicitement
                applyRawToDAC(wl_options[ledIdx], rawValue, CS);
            }
        }
    }
}