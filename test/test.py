import tkinter as tk
from tkinter import ttk, scrolledtext
import serial.tools.list_ports
import serial
import subprocess
import threading
import os
import shutil
import time

# --- CODE ARDUINO ---
ARDUINO_SKETCH = """
void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
}

void loop() {
  digitalWrite(LED_BUILTIN, HIGH);
  delay(200);
  digitalWrite(LED_BUILTIN, LOW);
  delay(200);
  digitalWrite(LED_BUILTIN, HIGH);
  delay(200);
  digitalWrite(LED_BUILTIN, LOW);
  delay(800);
  Serial.println("TEST SUCCESS: System is alive!");
}
"""

class BlinkUploader:
    def __init__(self, root):
        self.root = root
        self.root.title("Universal Arduino Diagnostic")
        self.root.geometry("600x500")
        
        # --- UI ---
        frame = tk.Frame(root, padx=20, pady=20)
        frame.pack(fill=tk.BOTH, expand=True)

        # 1. Port Selection
        tk.Label(frame, text="1. Select COM Port:", font=("Arial", 10, "bold")).pack(anchor="w")
        self.com_port = tk.StringVar()
        self.combo_ports = ttk.Combobox(frame, textvariable=self.com_port, values=self.get_ports())
        self.combo_ports.pack(fill=tk.X, pady=(0, 10))
        
        # 2. Board Selection (Le Nouveau Choix !)
        tk.Label(frame, text="2. Select Board Type:", font=("Arial", 10, "bold")).pack(anchor="w")
        self.board_type = tk.StringVar(value="arduino:avr:uno")
        
        btn_frame = tk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(0, 15))
        
        r1 = tk.Radiobutton(btn_frame, text="Arduino UNO", variable=self.board_type, 
                            value="arduino:avr:uno", font=("Arial", 11))
        r1.pack(side=tk.LEFT, padx=10)
        
        r2 = tk.Radiobutton(btn_frame, text="Arduino MEGA 2560", variable=self.board_type, 
                            value="arduino:avr:mega", font=("Arial", 11))
        r2.pack(side=tk.LEFT, padx=10)

        # 3. Action Button
        self.btn = tk.Button(frame, text="UPLOAD & TEST", bg="#007ACC", fg="white", 
                             font=("Arial", 12, "bold"), pady=10, command=self.start_process)
        self.btn.pack(fill=tk.X, pady=(0, 10))

        # 4. Logs
        tk.Label(frame, text="Process Log:").pack(anchor="w")
        self.log_text = scrolledtext.ScrolledText(frame, height=12, state=tk.DISABLED, bg="#f0f0f0")
        self.log_text.pack(fill=tk.BOTH, expand=True)

    def log(self, text):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def start_process(self):
        port = self.com_port.get()
        board_fqbn = self.board_type.get()
        
        if not port:
            self.log("ERROR: Please select a COM port.")
            return
        
        self.btn.config(state=tk.DISABLED, bg="#666")
        self.log(f"--- STARTING ON {port} FOR {board_fqbn} ---")
        threading.Thread(target=self.run_task, args=(port, board_fqbn), daemon=True).start()

    def run_task(self, port, board_fqbn):
        sketch_name = "SimpleBlink"
        if os.path.exists(sketch_name):
            shutil.rmtree(sketch_name)
        os.makedirs(sketch_name)
        
        file_path = os.path.join(sketch_name, f"{sketch_name}.ino")
        with open(file_path, "w") as f:
            f.write(ARDUINO_SKETCH)
        
        # COMMANDE DYNAMIQUE SELON LA CARTE CHOISIE
        self.log(f"Compiling for {board_fqbn}...")
        cmd = ["arduino-cli", "compile", "--upload", "-p", port, "-b", board_fqbn, sketch_name]
        
        try:
            process = subprocess.run(cmd, capture_output=True, text=True)
            if process.returncode != 0:
                self.log("UPLOAD FAILED:")
                self.log(process.stderr)
                self.root.after(0, lambda: self.btn.config(state=tk.NORMAL, bg="#AA0000", text="RETRY"))
                return
            else:
                self.log("UPLOAD SUCCESSFUL!")
        except FileNotFoundError:
            self.log("CRITICAL ERROR: 'arduino-cli' not found.")
            return

        # TEST SERIAL
        self.log("Testing Serial Connection...")
        try:
            time.sleep(2) 
            with serial.Serial(port, 115200, timeout=3) as ser:
                start = time.time()
                while time.time() - start < 5:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                    if "SUCCESS" in line:
                        self.log(f"RECEIVED: {line}")
                        self.log("--- SYSTEM OK ---")
                        self.root.after(0, lambda: self.btn.config(state=tk.NORMAL, bg="#00AA00", text="SYSTEM OK"))
                        return
                self.log("WARNING: Connected but no specific message received.")
                self.root.after(0, lambda: self.btn.config(state=tk.NORMAL, bg="#DDAA00"))
        except Exception as e:
            self.log(f"SERIAL ERROR: {e}")
            self.root.after(0, lambda: self.btn.config(state=tk.NORMAL, bg="#AA0000"))

if __name__ == "__main__":
    root = tk.Tk()
    app = BlinkUploader(root)
    root.mainloop()