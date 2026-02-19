import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import subprocess
import os
import time
import json  # Nouveau : pour sauvegarder la config

# --- CONFIGURATION ---
# Change ceci en "arduino:avr:mega" si tu utilises la grande carte !
ARDUINO_BOARD = "arduino:avr:uno"  
CONFIG_FILE = "lampion_config.json"

class LampionApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LAMPION | Manual LED Controller")
        
        # Intercepte la fermeture de la fenêtre
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        self.root.minsize(870, 470) 
        self.root.geometry("870x470")
        self.root.configure(bg='#121212')

        self.FONT_TITLE = ("Segoe UI", 11, "bold")      
        self.FONT_UI = ("Segoe UI", 9)                  
        self.FONT_DIGITAL = ("Consolas", 12, "bold")   
        self.FONT_NEXT = ("Segoe UI", 9, "bold")
        self.FONT_STATUS = ("Segoe UI", 7, "bold")
        
        self.COLOR_BG = '#121212'
        self.COLOR_CARD = '#1E1E1E'
        self.COLOR_TEXT = '#E0E0E0'
        
        self.COLOR_BTN_DEFAULT = "#262626"
        self.COLOR_BTN_SELECTED = "#AAAAAA" 
        self.COLOR_FG_DEFAULT = "#999999"
        self.COLOR_FG_SELECTED = "#121212"

        self.voltages = [0.000, 0.030, 0.050, 0.070, 0.100, 0.300, 0.500, 0.700, 
                         1.000, 1.500, 2.000, 2.500, 3.000, 3.500, 4.000, 4.500, 5.000]
        
        self.leds = [
            {"wl": "385", "color": "#7D00FF", "idx": 0, "btns": {}},
            {"wl": "420", "color": "#0033FF", "idx": 1, "btns": {}},
            {"wl": "490", "color": "#00CCFF", "idx": 2, "btns": {}},
            {"wl": "530", "color": "#00FF00", "idx": 3, "btns": {}},
            {"wl": "595", "color": "#FF0000", "idx": 4, "btns": {}}
        ]

        self.ser = None
        self.is_connected = False # Nouveau drapeau de connexion
        self.states = [False] * 5
        self.v_vars = [tk.StringVar(value="0.000") for _ in range(5)]
        
        self.setup_ui()
        self.load_last_port()

    def setup_ui(self):
        # --- Connection Bar ---
        conn_frame = tk.Frame(self.root, bg=self.COLOR_CARD, pady=5)
        conn_frame.pack(fill=tk.X)

        tk.Label(conn_frame, text="COM PORT:", fg=self.COLOR_TEXT, bg=self.COLOR_CARD, font=self.FONT_UI).pack(side=tk.LEFT, padx=10)
        self.port_combo = ttk.Combobox(conn_frame, values=[p.device for p in serial.tools.list_ports.comports()], font=self.FONT_UI, width=12)
        self.port_combo.pack(side=tk.LEFT, padx=5)

        self.btn_conn = tk.Button(conn_frame, text="UPLOAD AND CONNECT", bg="#333", fg="white", 
                                  relief="flat", padx=15, command=self.start_upload_and_connect, font=self.FONT_UI, cursor="hand2")
        self.btn_conn.pack(side=tk.LEFT, padx=15)

        # --- Main LED Grid Container ---
        self.main_frame = tk.Frame(self.root, bg=self.COLOR_BG, pady=10, padx=5)
        self.main_frame.pack(expand=True, fill=tk.BOTH)
        
        self.main_frame.rowconfigure(0, weight=1) 
        for i in range(5):
            self.main_frame.columnconfigure(i, weight=1)

        for i, led in enumerate(self.leds):
            col = tk.Frame(self.main_frame, bg=self.COLOR_CARD, padx=5, pady=8, 
                           highlightbackground="#333", highlightthickness=1)
            col.grid(row=0, column=i, sticky="nsew", padx=3)

            tk.Label(col, text=f"{led['wl']} nm", fg=led['color'], bg=self.COLOR_CARD, font=self.FONT_TITLE).pack(pady=(0, 2))

            btn_onoff = tk.Button(col, text="OFF", bg="#300", fg="white", relief="flat",
                                  width=12, height=1, font=self.FONT_UI, command=lambda idx=i: self.toggle_led(idx), cursor="hand2")
            btn_onoff.pack(pady=2)
            led['btn_onoff'] = btn_onoff

            status_lbl = tk.Label(col, text="PRESET", fg="#444", bg=self.COLOR_CARD, font=self.FONT_STATUS)
            status_lbl.pack()
            led['status_lbl'] = status_lbl

            ent = tk.Entry(col, textvariable=self.v_vars[i], justify='center', width=7, 
                           bg="#000", fg=led['color'], insertbackground="white", 
                           relief="flat", font=self.FONT_DIGITAL)
            ent.pack(pady=2)
            ent.bind("<Return>", lambda e, idx=i: self.send_update_manual(idx))

            # --- NOUVEAU PLACEMENT DU BOUTON NEXT STEP ---
            btn_next = tk.Button(col, text="NEXT STEP", bg="#333", fg="white", relief="flat",
                                 height=1, font=self.FONT_NEXT, command=lambda idx=i: self.next_voltage(idx), cursor="hand2")
            btn_next.pack(pady=(5, 5), fill=tk.X)

            # --- Presets Grid (Placé après) ---
            preset_wrapper = tk.Frame(col, bg=self.COLOR_CARD)
            preset_wrapper.pack(expand=True, fill=tk.BOTH)
            preset_container = tk.Frame(preset_wrapper, bg=self.COLOR_CARD)
            preset_container.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            
            for j, v in enumerate(self.voltages):
                r, c = divmod(j, 2)
                v_str = f"{v:.3f}"
                btn_v = tk.Button(preset_container, text=v_str, bg=self.COLOR_BTN_DEFAULT, fg=self.COLOR_FG_DEFAULT, 
                                  relief="flat", width=7, font=("Consolas", 8), 
                                  command=lambda val=v, idx=i: self.set_preset(idx, val), cursor="hand2")
                btn_v.grid(row=r, column=c, padx=1, pady=1)
                led['btns'][v_str] = btn_v
            
        for i in range(5): self.update_highlight(i)

    # --- Gestion de la fermeture / Déconnexion ---
    def disconnect_hardware(self):
        print("Disconnecting hardware: Turning all LEDs OFF...")
        if self.ser: 
            try:
                if self.ser.is_open:
                    # Envoi 0 volt pour éteindre les 5 canaux avant de couper
                    for i in range(5):
                        self.ser.write(b'D')
                        self.ser.write(bytearray([i, 0, 0])) 
                    time.sleep(0.1)
                    self.ser.close()
            except Exception as e:
                print(f"Error during shutdown: {e}")
                
        self.ser = None
        self.is_connected = False
        
        # Reset des boutons UI
        self.btn_conn.config(text="UPLOAD AND CONNECT", bg="#333")
        for i in range(5):
            self.states[i] = False
            self.leds[i]['btn_onoff'].config(text="OFF", bg="#300", fg="white")

    def on_closing(self):
        """ Appelé quand on clique sur la croix rouge """
        self.disconnect_hardware()
        self.root.destroy()

    # --- Gestion de la config (Port COM) ---
    def load_last_port(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    last_port = data.get("port", "")
                    available_ports = [p.device for p in serial.tools.list_ports.comports()]
                    if last_port in available_ports:
                        self.port_combo.set(last_port)
        except Exception:
            pass

    def save_last_port(self, port):
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump({"port": port}, f)
        except Exception:
            pass

    def update_highlight(self, led_idx):
        try:
            val_float = float(self.v_vars[led_idx].get())
            current_val = f"{val_float:.3f}"
        except ValueError:
            current_val = ""

        led = self.leds[led_idx]
        for btn in led['btns'].values():
            btn.config(bg=self.COLOR_BTN_DEFAULT, fg=self.COLOR_FG_DEFAULT)
        
        if current_val in led['btns']:
            led['btns'][current_val].config(bg=self.COLOR_BTN_SELECTED, fg=self.COLOR_FG_SELECTED)
            led['status_lbl'].config(text="PRESET", fg="#444")
        else:
            led['status_lbl'].config(text="MANUAL", fg="#888")

    def send_update_manual(self, idx):
        self.update_highlight(idx)
        self.send_update(idx)

    def set_preset(self, idx, val):
        self.v_vars[idx].set(f"{val:.3f}")
        self.update_highlight(idx)
        self.send_update(idx)

    def next_voltage(self, idx):
        try:
            current_v = float(self.v_vars[idx].get())
            for v in self.voltages:
                if v > current_v + 0.001:
                    self.set_preset(idx, v)
                    return
            self.set_preset(idx, self.voltages[0])
        except ValueError:
            self.set_preset(idx, self.voltages[0])

    def toggle_led(self, idx):
        # --- SAFETY CHECK: Prevent turning on if not connected ---
        if not self.is_connected:
            messagebox.showwarning("Disconnected", "Please UPLOAD AND CONNECT to the board first.")
            return

        self.states[idx] = not self.states[idx]
        color = self.leds[idx]['color']
        btn = self.leds[idx]['btn_onoff']
        
        if self.states[idx]:
            btn.config(text="ON", bg=color, fg="black" if color in ["#00FF00", "#00CCFF"] else "white")
        else:
            btn.config(text="OFF", bg="#300", fg="white")
            
        self.send_update(idx)

    # --- Communication (arduino-cli) ---
    def start_upload_and_connect(self):
        # Bascule la connexion si déjà connecté
        if self.is_connected:
            self.disconnect_hardware()
            return

        port = self.port_combo.get()
        if not port: return
        
        self.save_last_port(port)
        sketch_path = os.path.join("lampion_arduino", "lampion_arduino.ino")
        
        self.btn_conn.config(text="UPLOADING...", bg="#850", state=tk.DISABLED)
        self.root.update()
        
        try:
            cmd = ["arduino-cli", "compile", "--upload", "--fqbn", ARDUINO_BOARD, sketch_path, "-p", port]
            subprocess.run(cmd, check=True)
            
            self.btn_conn.config(text="CONNECTING...", bg="#850")
            time.sleep(2) 
            
            self.ser = serial.Serial(port, 115200, timeout=1)
            
            # Mise à jour UI post-connexion
            self.is_connected = True
            self.btn_conn.config(text="DISCONNECT", bg="#500", state=tk.NORMAL)
            
            # Synchronisation initiale : forcer toutes les LEDs aux valeurs actuelles de l'UI
            for i in range(5):
                self.send_update(i)
                
        except Exception as e:
            self.btn_conn.config(text="UPLOAD ERROR", bg="#500", state=tk.NORMAL)
            print(f"Error details: {e}")
            messagebox.showerror("Error", f"Upload failed:\n{e}")

    def send_update(self, idx):
        if not self.ser or not self.ser.is_open: return
        try:
            val_v = float(self.v_vars[idx].get()) if self.states[idx] else 0.0
            raw = int((val_v / 2.0) * (4095 / 2.5))
            raw = max(0, min(4095, raw))
            
            self.ser.write(b'D')
            self.ser.write(bytearray([idx, (raw >> 8) & 0xFF, raw & 0xFF]))
        except ValueError: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = LampionApp(root)
    root.mainloop()
