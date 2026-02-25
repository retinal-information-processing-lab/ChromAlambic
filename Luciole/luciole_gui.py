import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import os
import pandas as pd
import serial
import serial.tools.list_ports
import threading
import time
import struct
import subprocess
import datetime
from collections import deque

# --- CONFIGURATION ---
ARDUINO_BOARD     = "arduino:avr:uno"
CONFIG_FILE       = "luciole_config.json"

# Must mirror Arduino's BUFFER_SIZE and REFILL_THRESHOLD
ARDUINO_BUFFER_SIZE       = 100   # slots on Arduino (99 usable)
ARDUINO_REFILL_THRESHOLD  = 20    # Arduino asks for this many mixes at a time

# Message type bytes (Arduino -> Python)
MSG_REFILL   = 0x01
MSG_FREQ     = 0x02
MSG_TRIG_ERR = 0x03


class LucioleApp:
    def __init__(self, root):
        self.root = root
        self.root.title("LUCIOLE | Automated Sequence Controller")
        self.root.geometry("1100x750")
        self.root.minsize(1100, 750)
        self.root.configure(bg='#121212')
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- State ---
        self.is_initializing  = True
        self.is_connected     = False
        self.protocol_running = False
        self.ser              = None
        self.num_triggers     = 0

        # Frequency: detected by Arduino at runtime.
        self.dmd_freq_estimate  = tk.StringVar(value="Freq: --- Hz")
        self.detected_freq_hz   = None
        self.stim_duration      = tk.StringVar(value="Duration: --")
        self.total_sequence_len = 0

        self.vec_path = tk.StringVar()
        self.csv_path = tk.StringVar()
        self.com_port = tk.StringVar()

        self.available_wavelengths = [385, 420, 490, 530, 625]
        self.led_vars    = {wl: tk.BooleanVar(value=False) for wl in self.available_wavelengths}
        self.led_buttons = {}

        # Styles
        self.COLOR_BG   = '#121212'
        self.COLOR_CARD = '#1E1E1E'
        self.COLOR_TEXT = '#E0E0E0'
        self.LED_COLORS = {385: "#7D00FF", 420: "#0033FF", 490: "#00CCFF",
                           530: "#00FF00", 625: "#FF0000"}

        self.setup_ui()

        self.vec_path.trace_add("write", lambda *a: self.on_path_change("vec"))
        self.csv_path.trace_add("write", lambda *a: self.on_path_change("csv"))

        self.load_settings()
        self.update_table_columns()
        self.root.after(100, self.initial_load)
        self.root.after(200, self.finish_init)

    def finish_init(self):
        self.is_initializing = False

    # =========================================================================
    # UI SETUP
    # =========================================================================
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

        # Files
        file_frame = tk.LabelFrame(left_frame, text=" File Configuration ",
                                   bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        file_frame.pack(fill=tk.X, pady=(0, 10))
        for label, var, cmd in [("VEC:", self.vec_path, self.browse_vec),
                                 ("CSV:", self.csv_path, self.browse_csv)]:
            row = tk.Frame(file_frame, bg=self.COLOR_CARD)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, bg=self.COLOR_CARD, fg="#777", width=5).pack(side=tk.LEFT)
            tk.Entry(row, textvariable=var, bg="#000", fg="white",
                     relief="flat").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
            tk.Button(row, text="...", bg="#444", fg="white", command=cmd,
                      width=3, relief="flat").pack(side=tk.LEFT)

        # LEDs
        led_frame = tk.LabelFrame(left_frame, text=" LED Selection ",
                                  bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        led_frame.pack(fill=tk.X, pady=(0, 10))
        for wl in self.available_wavelengths:
            btn = tk.Button(led_frame, text=f"{wl}", bg="#300", fg="white", relief="flat",
                            command=lambda w=wl: self.toggle_led(w), width=4)
            btn.pack(side=tk.LEFT, padx=5, expand=True)
            self.led_buttons[wl] = btn

        # Palette viewer
        viewer_card = tk.LabelFrame(left_frame, text=" Color Palette Viewer ",
                                    bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=5, pady=5)
        viewer_card.pack(fill=tk.BOTH, expand=True)
        self.tree_container = tk.Frame(viewer_card, bg=self.COLOR_CARD)
        self.tree_container.pack(fill=tk.BOTH, expand=True)
        self.color_tree = ttk.Treeview(self.tree_container, show="headings")
        self.color_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.tree_container, orient=tk.VERTICAL,
                                  command=self.color_tree.yview)
        self.color_tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # --- RIGHT COLUMN ---
        right_frame = tk.Frame(main_container, bg=self.COLOR_BG)
        right_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Hardware control
        hw_frame = tk.LabelFrame(right_frame, text=" Hardware Control ",
                                 bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=10, pady=10)
        hw_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Label(hw_frame, text="COM Port:", bg=self.COLOR_CARD,
                 fg=self.COLOR_TEXT).pack(side=tk.LEFT)
        self.port_combo = ttk.Combobox(hw_frame, textvariable=self.com_port,
                                       values=self.get_ports(), width=10)
        self.port_combo.pack(side=tk.LEFT, padx=10)
        self.btn_initialize = tk.Button(hw_frame, text="UPLOAD & CONNECT", bg="#444",
                                        fg="white", command=self.unified_init,
                                        relief="flat", padx=20, font=("Segoe UI", 9, "bold"))
        self.btn_initialize.pack(side=tk.LEFT, padx=5)

        # Logs & status
        log_frame = tk.LabelFrame(right_frame, text=" System Logs ",
                                  bg=self.COLOR_CARD, fg=self.COLOR_TEXT, padx=10, pady=10)
        log_frame.pack(fill=tk.BOTH, expand=True)

        status_row = tk.Frame(log_frame, bg=self.COLOR_CARD)
        status_row.pack(fill=tk.X, pady=(0, 5))

        # Freq: clean read-only label, no box, no annotation
        self.lbl_freq = tk.Label(status_row, textvariable=self.dmd_freq_estimate,
                                 bg=self.COLOR_CARD, fg="#777", font=("Consolas", 10))
        self.lbl_freq.pack(side=tk.LEFT, padx=(0, 20))

        # Duration / remaining
        tk.Label(status_row, textvariable=self.stim_duration, bg=self.COLOR_CARD,
                 fg="#00FF00", font=("Arial", 10, "bold")).pack(side=tk.LEFT)

        status_bar_frame = tk.Frame(log_frame, bg=self.COLOR_CARD)
        status_bar_frame.pack(fill=tk.X)
        self.lbl_status = tk.Label(status_bar_frame, text="STATUS: IDLE",
                                   bg=self.COLOR_CARD, fg="#555",
                                   font=("Arial", 10, "bold"))
        self.lbl_status.pack(side=tk.LEFT)
        self.btn_export = tk.Button(status_bar_frame, text="EXPORT LOG", bg="#333",
                                    fg="white", relief="flat", command=self.export_log,
                                    font=("Segoe UI", 8, "bold"), cursor="hand2")
        self.btn_export.pack(side=tk.RIGHT)

        self.progress = ttk.Progressbar(log_frame, orient=tk.HORIZONTAL, mode='determinate')
        self.progress.pack(fill=tk.X, pady=5)

        self.log_text = tk.Text(log_frame, state=tk.DISABLED, bg="#000", fg="#00FF00",
                                font=("Consolas", 8), height=15)
        self.log_text.pack(fill=tk.BOTH, expand=True)

        # Style tags for coloured log lines
        self.log_text.tag_configure("warn",  foreground="#FFD700")
        self.log_text.tag_configure("error", foreground="#FF4444")
        self.log_text.tag_configure("info",  foreground="#00FF00")
        self.log_text.tag_configure("freq",  foreground="#00CCFF")

        self.btn_start = tk.Button(right_frame, text="RUN PROTOCOL", state=tk.DISABLED,
                                   bg="#333", fg="#555", command=self.start_protocol,
                                   font=("Arial", 12, "bold"), pady=10, relief="flat")
        self.btn_start.pack(fill=tk.X, pady=(10, 0))

    # =========================================================================
    # EXPORT LOG
    # =========================================================================
    def export_log(self):
        folder_path = filedialog.askdirectory(title="Select folder to save log")
        if not folder_path:
            return
        date_str = datetime.datetime.now().strftime("%Y%m%d")
        index = 1
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
            self.log(f"Log exported to {filename}")
            messagebox.showinfo("Export Success", f"Log saved:\n{filepath}")
        except Exception as e:
            self.log(f"Export failed: {e}", "error")
            messagebox.showerror("Export Error", str(e))

    # =========================================================================
    # HARDWARE INIT / CONNECT / DISCONNECT
    # =========================================================================
    def unified_init(self):
        if self.is_connected:
            self.disconnect_hardware()
            return
        port = self.com_port.get()
        if not port:
            messagebox.showwarning("Warning", "Select COM Port first.")
            return
        self.log(f"Starting initialization on {port}...")
        self.btn_initialize.config(text="UPLOADING...", bg="#850", state=tk.DISABLED)
        self.root.update()

        def run_task():
            try:
                sketch_path = os.path.join("luciole_arduino", "luciole_arduino.ino")
                cmd = ["arduino-cli", "compile", "--upload", "-p", port,
                       "--fqbn", ARDUINO_BOARD, sketch_path]
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    self.root.after(0, lambda: self.log("Flash SUCCESS! Connecting..."))
                    time.sleep(2.0)
                    self.root.after(0, lambda: self.connect_hardware(port))
                else:
                    self.root.after(0, lambda: [
                        self.log(f"Flash FAIL: {res.stderr}", "error"),
                        self.btn_initialize.config(text="INIT FAILED", bg="#500",
                                                   state=tk.NORMAL)])
            except Exception as e:
                self.root.after(0, lambda: [
                    self.log(f"CLI Error: {e}", "error"),
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
            self.log(f"Connected on {port}.")
            self.save_settings()
        except Exception as e:
            self.log(f"Connection error: {e}", "error")
            self.btn_initialize.config(text="CONN ERROR", bg="#500", state=tk.NORMAL)

    def disconnect_hardware(self):
        self.protocol_running = False
        time.sleep(0.1)
        if self.ser:
            try:
                if self.ser.is_open:
                    self.ser.close()
            except Exception:
                pass
        self.ser = None
        self.is_connected = False
        self.btn_initialize.config(text="UPLOAD & CONNECT", bg="#444")
        self.lbl_status.config(text="STATUS: IDLE", fg="#555")
        self.btn_start.config(state=tk.DISABLED, bg="#333", fg="#555")
        self.progress.configure(value=0)
        self.stim_duration.set("Duration: --")
        self.dmd_freq_estimate.set("Freq: --- Hz")
        self.detected_freq_hz = None
        self.log("Hardware disconnected.")

    # =========================================================================
    # PROTOCOL START
    # =========================================================================
    def start_protocol(self):
        try:
            self.log("--- SANITY CHECKS ---")
            selected_wl = [wl for wl, var in self.led_vars.items() if var.get()]
            if not selected_wl:
                self.log("ERROR: No LEDs selected.", "error")
                return

            # Load CSV
            if not self.csv_path.get():
                self.log("ERROR: No CSV selected.", "error")
                return
            df_csv = pd.read_csv(self.csv_path.get(), header=None)
            num_mixes_available = len(df_csv)
            if len(df_csv.columns) != len(selected_wl):
                self.log(f"COLUMN MISMATCH: CSV has {len(df_csv.columns)} columns, "
                         f"{len(selected_wl)} LEDs selected.", "error")
                return
            self.log(f"CSV loaded: {num_mixes_available} mixes, {len(selected_wl)} LEDs.")

            # Load VEC
            if not self.vec_path.get():
                self.log("ERROR: No VEC selected.", "error")
                return
            df_vec = pd.read_csv(self.vec_path.get(), sep=r'\s+', skiprows=1, header=None)
            sequence = df_vec[2].astype(int).tolist()
            num_triggers = len(sequence)
            self.log(f"VEC loaded: {num_triggers} triggers.")

            # Check max index
            max_idx = max(sequence)
            if max_idx >= num_mixes_available:
                msg = (f"CRITICAL: VEC calls index {max_idx} but CSV has only "
                       f"{num_mixes_available} rows!")
                self.log(msg, "error")
                messagebox.showerror("Sanity Check Failed", msg)
                return

            # Coverage check
            used   = set(sequence)
            unused = set(range(num_mixes_available)) - used
            if unused:
                self.log(f"WARNING: {len(unused)} CSV rows never used "
                         f"(sample: {list(unused)[:10]})", "warn")
            else:
                self.log("CHECK OK: All CSV rows used at least once.")

            # Build voltage lookup: raw_table[mix_index] = [uint16 per LED]
            # Column order in CSV = ascending wavelength order = selected_wl order
            raw_table = []
            for _, row in df_csv.iterrows():
                mix = []
                for v in row:
                    raw = int((float(v) / 2.0) * (4095 / 2.5))
                    mix.append(max(0, min(4095, raw)))
                raw_table.append(mix)

            # Build ordered mix stream from VEC sequence
            mix_stream = [raw_table[idx] for idx in sequence]

            # Reset freq display
            self.detected_freq_hz = None
            self.dmd_freq_estimate.set("Freq: --- Hz")
            self.stim_duration.set("Duration: --")
            self.total_sequence_len = num_triggers

            self.btn_start.config(state=tk.DISABLED)
            self.protocol_running = True
            threading.Thread(
                target=self.communication_thread,
                args=(selected_wl, mix_stream),
                daemon=True
            ).start()

        except Exception as e:
            self.log(f"Start Error: {e}", "error")
            messagebox.showerror("Error", str(e))

    # =========================================================================
    # COMMUNICATION THREAD
    # =========================================================================
    def communication_thread(self, selected_wl, mix_stream):
        """
        mix_stream: list of lists — mix_stream[i] = [uint16, ...] one per LED,
                    in ascending wavelength order (matches CSV column order).
        """
        try:
            total     = len(mix_stream)
            queue     = deque(mix_stream)
            ack_count = 0

            if not self.ser or not self.ser.is_open:
                return

            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.05)

            # Build LED mask — bit i = wl_options[i], same order as Arduino
            wl_options = [385, 420, 490, 530, 625]
            mask = 0
            for i, wl in enumerate(wl_options):
                if wl in selected_wl:
                    mask |= (1 << i)

            # Send 'S' + mask
            self.ser.write(b'S')
            self.ser.write(bytes([mask]))

            # Send initial buffer fill (ARDUINO_BUFFER_SIZE - 1 mixes)
            initial_fill = ARDUINO_BUFFER_SIZE - 1
            for _ in range(initial_fill):
                if not queue:
                    break
                mix = queue.popleft()
                for raw in mix:
                    self.ser.write(bytes([(raw >> 8) & 0xFF, raw & 0xFF]))

            # Wait for 'R' handshake
            self.log("Waiting for Arduino handshake...")
            start_wait = time.time()
            while True:
                if not self.protocol_running:
                    return
                if time.time() - start_wait > 10.0:
                    self.log("ERROR: Arduino handshake timeout.", "error")
                    return
                if self.ser.in_waiting:
                    b = self.ser.read(1)
                    if b == b'R':
                        break

            self.log("--------------------------------")
            self.log("  SYSTEM ARMED & WAITING.      ")
            self.log("  >>> START DMD STIMULUS NOW <<<")
            self.log("--------------------------------")

            # Message parser state
            rx_buf            = bytearray()
            timeout_threshold = 2.0
            last_msg_time     = time.time()
            first_trigger     = False

            # Main loop
            while ack_count < total:
                if not self.protocol_running:
                    return
                if self.ser is None:
                    return

                n = self.ser.in_waiting
                if n > 0:
                    rx_buf += self.ser.read(n)
                    last_msg_time = time.time()
                    if not first_trigger:
                        first_trigger = True
                        self.root.after(0, lambda: self.log("--> FIRST TRIGGER. Running..."))

                # Parse complete messages
                while rx_buf:
                    msg_type = rx_buf[0]

                    if msg_type == MSG_REFILL:
                        if len(rx_buf) < 2:
                            break
                        n_requested = rx_buf[1]
                        rx_buf = rx_buf[2:]
                        ack_count += n_requested
                        self._send_mixes(queue, n_requested)
                        pct = min(100, int(ack_count / total * 100))
                        self.root.after(0, lambda v=pct: self.progress.configure(value=v))
                        self._update_time_remaining(ack_count, total)

                    elif msg_type == MSG_FREQ:
                        if len(rx_buf) < 3:
                            break
                        hz = struct.unpack('>H', rx_buf[1:3])[0]
                        rx_buf = rx_buf[3:]
                        self.detected_freq_hz = hz
                        self.root.after(0, lambda f=hz: self._on_freq_detected(f))

                    elif msg_type == MSG_TRIG_ERR:
                        if len(rx_buf) < 5:
                            break
                        delta_us = struct.unpack('>I', rx_buf[1:5])[0]
                        rx_buf = rx_buf[5:]
                        delta_ms = delta_us / 1000.0
                        if self.detected_freq_hz:
                            expected_ms = 1000.0 / self.detected_freq_hz
                            self.root.after(0, lambda d=delta_ms, e=expected_ms:
                                self.log(
                                    f"WARNING: Trigger timing error! "
                                    f"Expected ~{e:.1f}ms, got {d:.2f}ms", "warn"))
                        else:
                            self.root.after(0, lambda d=delta_ms:
                                self.log(f"WARNING: Trigger timing error! "
                                         f"Interval: {d:.2f}ms", "warn"))
                    else:
                        # Unknown byte — discard and resync
                        rx_buf = rx_buf[1:]

                # Timeout detection
                if first_trigger and (time.time() - last_msg_time) > timeout_threshold:
                    self.log(f"Signal stopped (>{timeout_threshold}s silence).")
                    self.log(f"Ended at trigger {ack_count}/{total}.")
                    break

                time.sleep(0.001)

            # End report
            if ack_count >= total:
                self.log("DONE: Sequence completed (100%).")
            else:
                pct = int(ack_count / total * 100) if total > 0 else 0
                self.log(f"DONE: Stopped early ({pct}% played).")

            self.root.after(0, lambda: self.stim_duration.set("Finished."))

        except Exception as e:
            if self.protocol_running:
                self.log(f"Communication error: {e}", "error")
        finally:
            self.protocol_running = False
            self.root.after(0, lambda: self.btn_start.config(state=tk.NORMAL))

    def _send_mixes(self, queue, count):
        """Send `count` mixes from the queue to Arduino."""
        for _ in range(count):
            if not queue:
                break
            mix = queue.popleft()
            for raw in mix:
                self.ser.write(bytes([(raw >> 8) & 0xFF, raw & 0xFF]))

    def _on_freq_detected(self, hz):
        """Called on main thread when Arduino reports the detected frequency."""
        self.dmd_freq_estimate.set(f"Freq: {hz} Hz")
        self.detected_freq_hz = hz
        self.log(f"Frequency detected by Arduino: {hz} Hz", "freq")
        self._update_time_remaining(0, self.total_sequence_len)

    def _update_time_remaining(self, ack_count, total):
        """Update the duration/remaining label. Always called on main thread."""
        if self.detected_freq_hz and self.detected_freq_hz > 0 and total > 0:
            frames_left = total - ack_count
            secs = frames_left / self.detected_freq_hz
            mins = secs / 60.0
            if self.protocol_running:
                self.stim_duration.set(f"Remaining: {secs:.1f}s ({mins:.2f}min)")
            else:
                total_secs = total / self.detected_freq_hz
                total_mins = total_secs / 60.0
                self.stim_duration.set(
                    f"Duration: {total_secs:.1f}s ({total_mins:.2f}min)")

    # =========================================================================
    # HELPERS
    # =========================================================================
    def get_ports(self):
        return [p.device for p in serial.tools.list_ports.comports()]

    def browse_csv(self):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv")])
        if p:
            self.csv_path.set(p)

    def browse_vec(self):
        p = filedialog.askopenfilename(filetypes=[("VEC", "*.vec")])
        if p:
            self.vec_path.set(p)

    def load_settings(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    d = json.load(f)
                self.vec_path.set(d.get("vec_path", ""))
                self.csv_path.set(d.get("csv_path", ""))
                self.com_port.set(d.get("com_port", ""))
                for wl in d.get("selected_leds", []):
                    wl = int(wl)
                    if wl in self.led_vars:
                        self.led_vars[wl].set(True)
                        self.led_buttons[wl].config(
                            bg=self.LED_COLORS[wl],
                            fg="black" if wl in [490, 530] else "white")
            except Exception:
                pass

    def save_settings(self):
        d = {
            "vec_path":      self.vec_path.get(),
            "csv_path":      self.csv_path.get(),
            "com_port":      self.com_port.get(),
            "selected_leds": [wl for wl, var in self.led_vars.items() if var.get()]
        }
        with open(CONFIG_FILE, "w") as f:
            json.dump(d, f)

    def on_closing(self):
        self.disconnect_hardware()
        self.root.destroy()

    def log(self, message, level="info"):
        tag = {"warn": "warn", "error": "error", "freq": "freq"}.get(level, "info")
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"> {message}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def update_table_columns(self):
        selected_leds = [wl for wl, var in self.led_vars.items() if var.get()]
        cols = ["Index"] + [f"{wl}nm" for wl in selected_leds]
        self.color_tree["columns"] = cols
        total_tree_width = 380
        num_leds = max(len(selected_leds), 1)
        col_width = int((total_tree_width - 50) / num_leds)
        for col in cols:
            self.color_tree.heading(col, text=col)
            if col == "Index":
                self.color_tree.column(col, width=50, anchor=tk.CENTER, stretch=False)
            else:
                self.color_tree.column(col, width=col_width, anchor=tk.CENTER, stretch=True)

    def load_color_data(self, path):
        try:
            selected_leds = [wl for wl, var in self.led_vars.items() if var.get()]
            if not selected_leds:
                return
            df = pd.read_csv(path, header=None)
            if len(df.columns) != len(selected_leds):
                self.log(f"COLUMN MISMATCH: CSV({len(df.columns)}) vs "
                         f"LEDs({len(selected_leds)})", "warn")
                for item in self.color_tree.get_children():
                    self.color_tree.delete(item)
                return
            for item in self.color_tree.get_children():
                self.color_tree.delete(item)
            for idx, row in df.iterrows():
                self.color_tree.insert("", tk.END, values=[idx] + list(row))
            self.log(f"CSV preview: {len(df)} mixes loaded.")
        except Exception as e:
            self.log(f"CSV loading error: {e}", "error")

    def on_path_change(self, source):
        if self.is_initializing:
            return
        path = self.vec_path.get() if source == "vec" else self.csv_path.get()
        if os.path.exists(path) and os.path.isfile(path):
            if source == "csv":
                self.load_color_data(path)
            else:
                try:
                    with open(path, 'r') as f:
                        self.num_triggers = sum(1 for line in f) - 1
                    self.log(f"VEC: {os.path.basename(path)} ({self.num_triggers} triggers)")
                except Exception:
                    pass
            self.save_settings()

    def initial_load(self):
        self.log("--- Restoring Last Session ---")
        vec = self.vec_path.get()
        csv = self.csv_path.get()
        if vec and os.path.exists(vec):
            try:
                with open(vec, 'r') as f:
                    self.num_triggers = sum(1 for line in f) - 1
                self.log(f"VEC restored: {os.path.basename(vec)} "
                         f"({self.num_triggers} triggers)")
            except Exception:
                pass
        if csv and os.path.exists(csv):
            self.load_color_data(csv)

    def toggle_led(self, wl):
        is_active = not self.led_vars[wl].get()
        self.led_vars[wl].set(is_active)
        btn = self.led_buttons[wl]
        btn.config(bg=self.LED_COLORS[wl] if is_active else "#300",
                   fg="black" if is_active and wl in [490, 530] else "white")
        self.update_table_columns()
        if self.csv_path.get():
            self.load_color_data(self.csv_path.get())
        self.save_settings()


if __name__ == "__main__":
    root = tk.Tk()
    app  = LucioleApp(root)
    root.mainloop()
