# ChromAlambic | LED Control Suite

**ChromAlambic** is a high-performance optogenetics and imaging light-control suite. It consists of two specialized tools designed to interface with an Arduino-based DAC system (SPI 12-bit) for precise LED intensity management across five wavelengths (385nm, 420nm, 490nm, 530nm, 625nm).

## 1. System Overview

### 💡 Lampion (Manual Control)
* **Purpose:** Real-time, manual "mixing" of LED intensities.
* **Key Features:**
    * 5-column dashboard.
    * 17 voltage presets per channel for calibration of LEDs.
    * "Next Step" rapid cycling for quick intensity adjustments.
    * "Manual" mode for non-preset values.
* **Workflow:** Ideal for finding optimal light power or providing static stimulation during live observations.

### 🦋 Luciole (Automated Sequences)
* **Purpose:** High-speed synchronized light stimulation (up to 100Hz+).
* **Key Features:**
    * Synchronized `.VEC` (timing/indices) and `.CSV` (voltage mixes) file loading.
    * Unified Initialization: One-click Flash + Handshake.
    * Real-time progress monitoring and terminal feedback.
    * Keeps track of last vec and csv file used after shutdown.
* **Workflow:** Ideal for complex protocols where light must change in sync with a DMD, SLM, or camera frames.

---

## 📂 Project Structure

```text
ChromAlambic/
├── Lampion/
│   ├── lampion_gui.py           # Manual control interface
│   └── lampion_arduino/         # Arduino driver & SPI library
│       ├── lampion_driver.ino
│       ├── ColorSetupLib.h
│       └── ColorSetupLib.cpp
├── Luciole/
│   ├── luciole_gui.py           # Automated sequence interface
│   └── luciole_arduino/         # Arduino driver & SPI library
│       ├── luciole_driver.ino
│       ├── ColorSetupLib.h
│       └── ColorSetupLib.cpp
└── data/                        # Shared folder for .VEC and .CSV files
```

---

## 🛠 Installation Guide (Windows)

### Prerequisites

1.  **Anaconda (or Miniconda)**: Download and install from [anaconda.com](https://www.anaconda.com/download).
2.  **Arduino CLI**: Required for the "Unified Initialization" feature.
    * Download the Windows ZIP file from [Arduino CLI Releases](https://arduino.github.io/arduino-cli/latest/installation/).
    * Extract `arduino-cli.exe` to a permanent folder (e.g., `C:\Program Files\ArduinoCLI`).
    * **CRITICAL STEP (Add to PATH):**
        1. Press `Win + S` and search for **"Edit the system environment variables"**.
        2. Click **Environment Variables**.
        3. Under "System variables", select **Path** and click **Edit**.
        4. Click **New** and paste the path to your folder (e.g., `C:\Program Files\ArduinoCLI`).
        5. Click OK to save.
    * Open a **new** terminal and run this command to install the AVR core:
        ```cmd
        arduino-cli core install arduino:avr
        ```

### Step 1: Environment Setup (Conda)
1. Open the **Anaconda Prompt** (Search for "Anaconda Prompt" in the Windows Start Menu).
2. Navigate to your project folder (optional, but good practice).
3. Run the following commands:

   **Create the environment:**
   ```cmd
   conda create -n chromalambic python=3.10 -y
   ```

   **Activate the environment:**
   ```cmd
   conda activate chromalambic
   ```

   **Install dependencies:**
   *(Navigate to the `ChromAlambic` root folder first)*
   ```cmd
   pip install pyserial pandas
   ```

### Step 2: Running the Software

#### To use Lampion:
```bash
python Lampion/lampion_gui.py
```
1. Select the **COM Port**.
2. Click **INITIALIZE SYSTEM**. The software flashes the driver and connects automatically.

#### To use Luciole:
```bash
python Luciole/luciole_gui.py
```
1. Select the **COM Port**.
2. Click **INITIALIZE SYSTEM**.
3. Load your `.VEC` and `.CSV` files.
4. Activate the LEDs used in your CSV (the order must match the selection).
5. Click **RUN PROTOCOL**.

---

## ⚠️ Hardware & Safety
* **Voltage Mapping:** Logic is hard-coded for a 12-bit DAC where 0.0V–5.0V maps to 0–4095.
* **Protocol Validation:** **Luciole** will prevent execution and log a `MISMATCH` error if the number of active LEDs does not match the number of columns in your CSV.
* **Emergency Stop:**
    * **Lampion:** Use the individual **OFF** buttons.
    * **Luciole:** Click **DISCONNECT** to immediately halt the sequence and close communication.
