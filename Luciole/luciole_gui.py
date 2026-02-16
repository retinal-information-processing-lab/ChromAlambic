import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import pandas as pd
import serial
import serial.tools.list_ports
import threading
import time
import subprocess
import datetime # Nouveau : pour gérer la date de l'export

# --- CONFIGURATION ---
ARDUINO_BOARD = "arduino:avr:uno" 
CONFIG_FILE = "luciole_config.json"

class LucioleApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LUCIOLE | Automated Sequence Controller")
        self.root.geometry("1100x750")
        self.root.minsize(1100, 750)
        self.root.configure(bg='#121212')

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- Variables ---
        self.is_initializing = True  
        self.is_connected = False
        self.protocol_running = False 
        self.ser = None
        self.num_triggers = 0
        
        self.vec_path = tk.StringVar()
        self.csv_path = tk.StringVar()
        self.com_port = tk.StringVar()
        self.dmd_freq = tk.StringVar(value="100")
        self.stim_duration = tk.StringVar(value="Duration: 0.0s")
        
        self.available_wavelengths = [385, 420, 490, 530, 625]
        self.led_vars = {wl: tk.BooleanVar(value=False) for wl in self.available_wavelengths}
        self.led_buttons = {}
        
        # Styles
        self.COLOR_BG = '#121212'
        self.COLOR_CARD = '#1E1E1E'
        self.COLOR_TEXT = '#E0E0E0'
        self.LED_COLORS = {385: "#7D00FF", 420: "#0033FF", 490: "#00CCFF", 530: "#00FF00", 625: "#FF0000"}

        self.setup_ui()

        # Traces
        self.vec_path.trace_add("write", lambda *args: self.on_path_change("vec"))
        self.csv_path.trace_add("write", lambda *args: self.on_path_change("csv"))
        self.dmd_freq.trace_add("write", lambda *args: self.calculate_duration())

        self.load_settings()
        self.update_table_columns()
        self.root.after(100, self.initial_load)
        self.root.after(200, self.finish_init)

    def finish_init(self):
        self.is_initializing = False

    def setup_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("Treeview", background=self.COLOR_CARD, foreground=self.COLOR_TEXT, 
                        fieldbackground=self.COLOR_CARD, borderwidth=0)
        style.configure("Treeview.Heading", background="#333", foreground="white", relief="flat")

        main_container = tk.Frame(self.root, bg=self.COLOR_BG, padx=10, pady=10)
        main_container.pack(fill=tk.BOTH, expand=True)

        # --- LEFT COLUMN ---
        left_frame = tk.Frame(main_container, bg=self.COLOR_BG, width=400)
        left_frame.pack_propagate(False)
        left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=False, padx=(0, 10))

        # Files Card
        file_frame = tk.LabelFrame(left_frame, text=" File Configuration ", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        file_frame.pack(fill=tk.X, pady=(0, 10))
        for label, var, cmd in [("VEC:", self.vec_path, self.browse_vec), ("CSV:", self.csv_path, self.browse_csv)]:
            row = tk.Frame(file_frame, bg=self.COLOR_CARD)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, bg=self.COLOR_CARD, fg="#777", width=5).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=var, bg="#000", fg="white", relief="flat").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            tk.Button(row, text="...", bg="#444", fg="white", command=cmd, width=3, relief="flat").pack(side=tk.LEFT)

        # LEDs Card
        led_frame = tk.LabelFrame(left_frame, text=" LED Selection ", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        led_frame.pack(fill=tk.X, pady=(0, 10))
        for wl in self.available_wavelengths:
            btn = tk.Button(led_frame, text=f"{wl}", bg="#300", fg="white", relief="flat", 
                            command=lambda w=wl: self.toggle_led(w), width=4)
            btn.pack(side=tk.LEFT, padx=5, expand=True)
            self.led_buttons[wl] = btn

        # Viewer Card
        viewer_card = tk.LabelFrame(left_frame, text=" Color Palette Viewer ", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        viewer_card.pack(fill=tk.BOTH, expand=True)
        self.tree_container = tk.Frame(viewer_card, bg=self.COLOR_CARD)
        self.tree_container.pack(fill=tk.BOTH, expand=True)
        self.color_tree = ttk.Treeview(self.tree_container, show="headings")
        self.color_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.tree_container, orient=tk.VERTICAL, command=self.color_tree.yview)
        self.color_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- RIGHT COLUMN ---
        right_frame = tk.Frame(main_container, bg=self.COLOR_BG)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Hardware Control
        hw_frame = tk.LabelFrame(right_frame, text=" Hardware Control ", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=10, pady=10)
        hw_frame.pack(fill=tk.X, pady=(0, 10))

        tk.Label(hw_frame, text="COM Port:", bg=self.COLOR_CARD, fg=self.COLOR_TEXT).pack(side=tk.LEFT)
        self.port_combo = ttk.Combobox(hw_frame, textvariable=self.com_port, values=self.get_ports(), width=10)
        self.port_combo.pack(side=tk.LEFT, padx=10)
        
        self.btn_initialize = tk.Button(hw_frame, text="UPLOAD & CONNECT", bg="#444", fg="white", 
                                       command=self.unified_init, relief="flat", padx=20, font=("Segoe UI", 9, "bold"))
        self.btn_initialize.pack(side=tk.LEFT, padx=5)

        # Logs & Status
        log_frame = tk.LabelFrame(right_frame, text=" System Logs ", bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        status_row = tk.Frame(log_frame, bg=self.COLOR_CARD)
        status_row.pack(fill=tk.X, pady=(0, 5))
        tk.Label(status_row, text="Freq (Hz):", bg=self.COLOR_CARD, fg="#777").pack(side=tk.LEFT)
        tk.Entry(status_row, textvariable=self.dmd_freq, bg="#000", fg="white", width=6, relief="flat").pack(side=tk.LEFT, padx=5)
        
        tk.Label(status_row, textvariable=self.stim_duration, bg=self.COLOR_CARD, fg="#00FF00", font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=20)
        
        # --- NOUVEAU CONTENEUR POUR LE STATUT ET L'EXPORT LOG ---
        status_bar_frame = tk.Frame(log_frame, bg=self.COLOR_CARD)
        status_bar_frame.pack(fill=tk.X)
        
        self.lbl_status = tk.Label(status_bar_frame, text="STATUS: IDLE", bg=self.COLOR_CARD, fg="#555", font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT)
        
        self.btn_export = tk.Button(status_bar_frame, text="EXPORT LOG", bg="#333", fg="white", relief="flat", 
                                    command=self.export_log, font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.btn_export.pack(side=tk.RIGHT)
        # --------------------------------------------------------

        self.progress = ttk.Progressbar(log_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)

        self.log_text = tk.Text(log_frame, state=tk.DISABLED, bg="#000", fg="#00FF00", font=("Consolas", 8), height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        self.btn_start = tk.Button(right_frame, text="RUN PROTOCOL", state=tk.DISABLED, bg="#333", fg="#555", 
                                   command=self.start_protocol, font=("Arial", 12, "bold"), pady=10, relief="flat")
        self.btn_start.pack(fill=tk.X, pady=(10, 0))

    # --- LOGIC ---

    def export_log(self):
        """ Fonction pour exporter le log au format log_Luciole_YYYYMMDD_0X.txt """
        folder_path = filedialog.askdirectory(title="Select folder to save log")
        if not folder_path:
            return # Annulé par l'utilisateur
            
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        index = 1
        
        # Recherche du prochain nom de fichier disponible
        while True:
            filename = f"log_Luciole_{date_str}_{index:02d}.txt"
            filepath = os.path.join(folder_path, filename)
            if not os.path.exists(filepath):
                break
            index += 1
            
        try:
            log_content = self.log_text.get("1.0", tk.END)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write("--- LUCIOLE SYSTEM LOG ---\n")
                f.write(f"Date: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"VEC File: {self.vec_path.get()}\n")
                f.write(f"CSV File: {self.csv_path.get()}\n")
                f.write("--------------------------\n\n")
                f.write(log_content)
                
            self.log(f"Log exported successfully to {filename}")
            messagebox.showinfo("Export Success", f"Log correctly saved in:\n{filepath}")
        except Exception as e:
            self.log(f"Failed to export log: {e}")
            messagebox.showerror("Export Error", f"Could not save the log file:\n{e}")

    def unified_init(self):
        if self.is_connected:
            self.disconnect_hardware()
            return

        port = self.com_port.get()
        if not port:
            messagebox.showwarning("Warning", "Select COM Port first.")
            return

        self.log(f"Starting System Initialization on {port}...")
        self.btn_initialize.config(text="UPLOADING...", bg="#850", state=tk.DISABLED)
        self.root.update()

        def run_task():
            try:
                sketch_path = os.path.join("luciole_arduino", "luciole_arduino.ino") 
                cmd = ["arduino-cli", "compile", "--upload", "-p", port, "--fqbn", ARDUINO_BOARD, sketch_path]
                res = subprocess.run(cmd, capture_output=True, text=True)
                
                if res.returncode == 0:
                    self.root.after(0, lambda: self.log("Flash SUCCESS! Handshaking..."))
                    time.sleep(2.0)
                    self.root.after(0, lambda: self.connect_hardware(port))
                else:
                    self.root.after(0, lambda: [self.log(f"Flash FAIL: {res.stderr}"), 
                                                self.btn_initialize.config(text="INIT FAILED", bg="#500", state=tk.NORMAL)])
            except Exception as e:
                self.root.after(0, lambda: [self.log(f"CLI Error: {e}"), 
                                            self.btn_initialize.config(text="ERROR", bg="#500", state=tk.NORMAL)])

        threading.Thread(target=run_task, daemon=True).start()

    def connect_hardware(self, port):
        try:
            self.ser = serial.Serial(port, 115200, timeout=1)
            time.sleep(1)
            self.is_connected = True
            self.btn_initialize.config(text="DISCONNECT", bg="#500", state=tk.NORMAL)
            self.lbl_status.config(text="STATUS: CONNECTED", fg="#00FF00")
            self.btn_start.config(state=tk.NORMAL, bg="#050", fg="white")
            self.log(f"Hardware Connected on {port}.")
            self.save_settings()
        except Exception as e:
            self.log(f"Connection error: {e}")
            self.btn_initialize.config(text="CONN ERROR", bg="#500", state=tk.NORMAL)

    def disconnect_hardware(self):
        self.protocol_running = False 
        time.sleep(0.1) 
        if self.ser: 
            try:
                if self.ser.is_open:
                    self.ser.write(b'S')
                    self.ser.write(bytearray([0, 0])) 
                    time.sleep(0.1)
                    self.ser.close()
            except Exception: pass
        self.ser = None
        self.is_connected = False
        self.btn_initialize.config(text="UPLOAD & CONNECT", bg="#444")
        self.lbl_status.config(text="STATUS: IDLE", fg="#555")
        self.btn_start.config(state=tk.DISABLED, bg="#333", fg="#555")
        self.progress.configure(value=0)
        self.calculate_duration() 
        self.log("Hardware disconnected.")

    def start_protocol(self):
        # 1. Loading Phase
        try:
            self.log("--- STARTING SANITY CHECKS ---")
            selected_wl = [wl for wl, var in self.led_vars.items() if var.get()]
            
            # --- Load CSV ---
            if not self.csv_path.get():
                self.log("ERROR: No CSV selected.")
                return
            df_csv = pd.read_csv(self.csv_path.get(), header=None)
            num_mixes_available = len(df_csv)
            self.log(f"CSV loaded: {num_mixes_available} mixes available.")

            # --- Load VEC ---
            if not self.vec_path.get():
                self.log("ERROR: No VEC selected.")
                return
            df_vec = pd.read_csv(self.vec_path.get(), sep='\s+', skiprows=1, header=None)
            sequence = df_vec[2].astype(int).tolist()
            num_triggers = len(sequence)
            self.log(f"VEC loaded: {num_triggers} triggers found.")

            # --- CHECK 1: Max Index vs CSV Length ---
            max_index_in_vec = max(sequence)
            if max_index_in_vec >= num_mixes_available:
                error_msg = f"CRITICAL: VEC calls index {max_index_in_vec}, but CSV has only {num_mixes_available} rows!"
                self.log(error_msg)
                messagebox.showerror("Sanity Check Failed", error_msg + "\n(Indices are 0-based)")
                return # Arrêt immédiat

            # --- CHECK 2: Coverage Check (All colors used?) ---
            used_indices = set(sequence)
            all_indices = set(range(num_mixes_available))
            unused_indices = all_indices - used_indices
            
            if len(unused_indices) == 0:
                self.log("CHECK OK: All CSV colors are used at least once.")
            else:
                self.log(f"WARNING: {len(unused_indices)} CSV rows are NEVER used in this VEC sequence.")
                self.log(f"Unused indices (sample): {list(unused_indices)[:10]}...")

            # --- Preparation Data ---
            voltage_table = []
            for _, row in df_csv.iterrows():
                for v in row:
                    raw = int((float(v) / 2.0) * (4095 / 2.5))
                    voltage_table.append(max(0, min(4095, raw)))

            # Go !
            self.btn_start.config(state=tk.DISABLED)
            self.protocol_running = True
            threading.Thread(target=self.communication_thread, args=(selected_wl, voltage_table, sequence), daemon=True).start()

        except Exception as e: 
            self.log(f"Start Error: {e}")
            messagebox.showerror("Error", str(e))

    def communication_thread(self, selected_wl, voltage_table, sequence):
        try:
            # --- 1. SETUP PHASE ---
            mask = 0
            wl_order = [385, 420, 490, 530, 625]
            for i, wl in enumerate(wl_order):
                if wl in selected_wl: mask |= (1 << i)
            
            if not self.ser or not self.ser.is_open: return

            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.1)

            # Envoi Configuration
            self.ser.write(b'S')
            self.ser.write(bytearray([mask, len(voltage_table) // len(selected_wl)]))
            for val in voltage_table: 
                self.ser.write(bytearray([(val >> 8) & 0xFF, val & 0xFF]))
            
            # Attente Handshake
            start_wait = time.time()
            while self.ser.read() != b'R': 
                if not self.protocol_running: return 
                if time.time() - start_wait > 5.0:
                    self.log("ERROR: Arduino handshake timeout.")
                    return
            
            # --- 2. PRE-REMPLISSAGE DU BUFFER ---
            total_sequence = len(sequence)
            sent_count = 0
            ack_count = 0
            BUFFER_LIMIT = 100 

            initial_fill = min(total_sequence, BUFFER_LIMIT)
            for i in range(initial_fill):
                if not self.protocol_running: return
                self.ser.write(bytearray([sequence[sent_count] & 0xFF]))
                sent_count += 1

            self.log("--------------------------------")
            self.log("  SYSTEM ARMED & WAITING.     ")
            self.log("  >>> START DMD STIMULUS NOW <<<")
            self.log("--------------------------------")
            
            # --- 3. PARAMÈTRES DE SURVEILLANCE ---
            try:
                freq = float(self.dmd_freq.get())
                if freq <= 0: freq = 100.0
            except: freq = 100.0

            expected_period = 1.0 / freq         
            warning_threshold = expected_period * 3.0 # Warning si petit lag
            timeout_threshold = 2.0              # Arrêt propre si silence > 2s
            
            # État du système
            first_trigger_detected = False
            last_ack_time = time.time()
            
            # --- 4. BOUCLE PRINCIPALE ---
            while ack_count < total_sequence:
                if not self.protocol_running: return 
                if self.ser is None: return

                current_time = time.time()

                # A. Lecture des confirmations (ACKs)
                if self.ser.in_waiting:
                    data = self.ser.read(self.ser.in_waiting)
                    ack_count += len(data)
                    
                    if not first_trigger_detected:
                        first_trigger_detected = True
                        self.log(f"--> FIRST TRIGGER RECEIVED. Running...")
                    else:
                        # Warning seulement pour les petits hoquets (lag)
                        gap = current_time - last_ack_time
                        if gap > warning_threshold:
                            self.log(f"WARNING: Irregular gap detected ({gap*1000:.1f}ms).")

                    last_ack_time = current_time

                    # Update UI
                    pct = int((ack_count / total_sequence) * 100)
                    self.root.after(0, lambda v=pct: self.progress.configure(value=v))
                    frames_left = total_sequence - ack_count
                    time_left = frames_left / freq
                    self.root.after(0, lambda t=time_left: self.stim_duration.set(f"Remaining: {t:.1f}s"))

                # B. Gestion de l'arrêt du signal (Fin de stim ou Pause longue)
                if first_trigger_detected:
                    if (current_time - last_ack_time) > timeout_threshold:
                        # Ce n'est plus une erreur, c'est considéré comme une fin normale
                        self.log(f"Signal stopped (> {timeout_threshold}s).")
                        self.log(f"Ending protocol at frame {ack_count}/{total_sequence}.")
                        break # On sort de la boucle proprement

                # C. Envoi de la suite
                try:
                    while (sent_count < total_sequence) and ((sent_count - ack_count) < BUFFER_LIMIT):
                        if not self.protocol_running: return
                        self.ser.write(bytearray([sequence[sent_count] & 0xFF]))
                        sent_count += 1
                except (OSError, AttributeError):
                    return
                
                time.sleep(0.001) 
            
            # --- RAPPORT DE FIN ---
            if ack_count >= total_sequence:
                self.log("DONE: Sequence completed (100%).")
            else:
                self.log(f"DONE: Stopped early ({int(ack_count/total_sequence*100)}% played).")
            
            self.root.after(0, lambda: self.stim_duration.set("Finished."))

        except Exception as e: 
            if self.protocol_running:
                self.log(f"Error: {e}")
        finally: 
            self.protocol_running = False
            self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL))

    # --- HELPERS ---
    def get_ports(self): return [p.device for p in serial.tools.list_ports.comports()]
    def browse_csv(self):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if p: self.csv_path.set(p)
    def browse_vec(self):
        p = filedialog.askopenfilename(filetypes=[("VEC", "*.vec")])
        if p: self.vec_path.set(p)
    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    d = json.load(f)
                    self.vec_path.set(d.get("vec_path", ""))
                    self.csv_path.set(d.get("csv_path", ""))
                    self.dmd_freq.set(d.get("dmd_freq", "100"))
                    self.com_port.set(d.get("com_port", ""))
                    for wl in d.get("selected_leds", []):
                        if int(wl) in self.led_vars:
                            self.led_vars[int(wl)].set(True)
                            self.led_buttons[int(wl)].config(bg=self.LED_COLORS[int(wl)], fg="black" if int(wl) in [490, 530] else "white")
            except: pass
    def save_settings(self):
        d = {
            "vec_path": self.vec_path.get(), 
            "csv_path": self.csv_path.get(), 
            "dmd_freq": self.dmd_freq.get(), 
            "com_port": self.com_port.get(),
            "selected_leds": [wl for wl, var in self.led_vars.items() if var.get()]
        }
        with open(CONFIG_FILE, "w") as f: json.dump(d, f)
    def on_closing(self):
        self.disconnect_hardware()
        self.root.destroy()

    def log(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"> {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)
    def update_table_columns(self):
        selected_leds = [wl for wl, var in self.led_vars.items() if var.get()]
        cols = ["Index"] + [f"{wl}nm" for wl in selected_leds]
        self.color_tree["columns"] = cols
        total_tree_width = 380 
        num_leds = len(selected_leds) if len(selected_leds) > 0 else 1
        col_width = int((total_tree_width - 50) / num_leds)
        for col in cols:
            self.color_tree.heading(col, text=col)
            if col == "Index": self.color_tree.column(col, width=50, anchor=tk.CENTER, stretch=False)
            else: self.color_tree.column(col, width=col_width, anchor=tk.CENTER, stretch=True)
    def load_color_data(self, path):
        try:
            selected_leds = [wl for wl, var in self.led_vars.items() if var.get()]
            if not selected_leds: return
            df = pd.read_csv(path, header=None)
            if len(df.columns) != len(selected_leds):
                self.log(f"COLUMN MISMATCH: CSV({len(df.columns)}) vs LEDs({len(selected_leds)})")
                for item in self.color_tree.get_children(): self.color_tree.delete(item)
                return
            for item in self.color_tree.get_children(): self.color_tree.delete(item)
            for idx, row in df.iterrows(): self.color_tree.insert("", tk.END, values=[idx] + list(row))
            self.log(f"Success: {len(df)} mixes loaded.")
        except Exception as e: self.log(f"CSV Loading Error: {e}")
    def on_path_change(self, source):
        if self.is_initializing: return
        path = self.vec_path.get() if source == "vec" else self.csv_path.get()
        if os.path.exists(path) and os.path.isfile(path):
            if source == "csv": self.load_color_data(path)
            else: 
                try:
                    with open(path, 'r') as f: self.num_triggers = sum(1 for line in f) - 1
                    self.log(f"VEC loaded: {os.path.basename(path)} ({self.num_triggers} triggers)")
                    self.calculate_duration()
                except: pass
            self.save_settings()
    def initial_load(self):
        self.log("--- Initializing Last Session ---")
        csv, vec = self.csv_path.get(), self.vec_path.get()
        if vec and os.path.exists(vec):
            try:
                with open(vec, 'r') as f: self.num_triggers = sum(1 for line in f) - 1
                self.log(f"VEC Restored: {os.path.basename(vec)}")
                self.calculate_duration()
            except: pass
        if csv and os.path.exists(csv): self.load_color_data(csv)
    def toggle_led(self, wl):
        is_active = not self.led_vars[wl].get()
        self.led_vars[wl].set(is_active)
        btn = self.led_buttons[wl]
        btn.config(bg=self.LED_COLORS[wl] if is_active else "#300", 
                   fg="black" if is_active and wl in [490, 530] else "white")
        self.update_table_columns()
        if self.csv_path.get(): self.load_color_data(self.csv_path.get())
        self.save_settings()
    def calculate_duration(self):
        try:
            freq = float(self.dmd_freq.get())
            if freq > 0 and self.num_triggers > 0: self.stim_duration.set(f"Duration: {self.num_triggers / freq:.2f}s")
            else: self.stim_duration.set("Duration: 0.0s")
        except: pass

if __name__ == "__main__":
    root = tk.Tk()
    app = LucioleApp(root)
    root.mainloop()