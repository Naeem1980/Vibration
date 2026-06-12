import time
import os
import re
import threading
from datetime import datetime

import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from plyer import accelerometer

from kivy.app import App
from kivy.clock import Clock
from kivy.utils import platform
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput


if platform == "android":
    from android.storage import primary_external_storage_path
    OUTPUT_FOLDER = os.path.join(
        primary_external_storage_path(),
        "Download",
        "VibrateMe"
    )
else:
    OUTPUT_FOLDER = "."


DEFAULT_RECORD_TIME = 10.0
DEFAULT_TARGET_FS = 300
MAX_RECOMMENDED_TARGET_FS = 300
DEFAULT_HIGHPASS_CUTOFF = 5.0


def estimate_requested_fs(target_fs):
    calibration_target = np.array([10, 20, 50, 100, 150, 200, 250, 300])
    calibration_request = np.array([10, 20, 50, 100, 150, 200, 400, 500])
    return float(np.interp(target_fs, calibration_target, calibration_request))


def safe_filename(text):
    text = text.strip()
    if text == "":
        text = "Measurement"
    return re.sub(r"[^A-Za-z0-9_-]+", "_", text)


class PocketVibrationFFT(App):

    def build(self):
        self.timestamps = []
        self.ax_data = []
        self.ay_data = []
        self.az_data = []

        self.recording = False
        self.sample_thread = None

        layout = BoxLayout(orientation="vertical", padding=10, spacing=8)

        self.status = Label(
            text=(
                "Pocket vibration estimator\n"
                f"Max recommended FFT sample rate: {MAX_RECOMMENDED_TARGET_FS} Hz\n"
                "Output: velocity spectrum in mm/s peak"
            )
        )

        self.name_input = TextInput(
            text="Measurement",
            multiline=False,
            hint_text="Measurement name"
        )

        self.fs_input = TextInput(
            text=str(DEFAULT_TARGET_FS),
            multiline=False,
            input_filter="float",
            hint_text="Target sample rate / Hz"
        )

        self.cutoff_input = TextInput(
            text=str(DEFAULT_HIGHPASS_CUTOFF),
            multiline=False,
            input_filter="float",
            hint_text="High-pass cutoff / Hz"
        )

        self.record_time_input = TextInput(
            text=str(DEFAULT_RECORD_TIME),
            multiline=False,
            input_filter="float",
            hint_text="Recording length / s"
        )

        self.start_button = Button(text="START RECORDING")
        self.start_button.bind(on_press=self.start_recording)

        self.fft_button = Button(text="CREATE FFT")
        self.fft_button.bind(on_press=self.create_fft)

        layout.add_widget(self.status)

        layout.add_widget(Label(text="Measurement name"))
        layout.add_widget(self.name_input)

        layout.add_widget(Label(text="Target sample rate / Hz"))
        layout.add_widget(self.fs_input)

        layout.add_widget(Label(text="High-pass cutoff / Hz"))
        layout.add_widget(self.cutoff_input)

        layout.add_widget(Label(text="Recording length / s"))
        layout.add_widget(self.record_time_input)

        layout.add_widget(self.start_button)
        layout.add_widget(self.fft_button)

        return layout

    def start_recording(self, instance):
        if self.recording:
            self.status.text = "Already recording."
            return

        try:
            target_fs = float(self.fs_input.text)
            self.highpass_cutoff = float(self.cutoff_input.text)
            self.record_time = float(self.record_time_input.text)
        except ValueError:
            self.status.text = "Invalid input."
            return

        if target_fs > MAX_RECOMMENDED_TARGET_FS:
            target_fs = MAX_RECOMMENDED_TARGET_FS
            self.fs_input.text = str(MAX_RECOMMENDED_TARGET_FS)

        if self.highpass_cutoff < 0.1:
            self.highpass_cutoff = 0.1
            self.cutoff_input.text = "0.1"

        if self.record_time < 1.0:
            self.record_time = 1.0
            self.record_time_input.text = "1.0"

        self.target_fs = target_fs
        self.requested_fs = estimate_requested_fs(target_fs)
        self.requested_dt = 1 / self.requested_fs

        self.timestamps = []
        self.ax_data = []
        self.ay_data = []
        self.az_data = []

        try:
            accelerometer.enable()
        except Exception as e:
            self.status.text = f"Could not enable accelerometer:\n{e}"
            return

        self.recording = True

        self.status.text = (
            f"Recording for {self.record_time:.1f} s...\n"
            f"Target fs: {target_fs:.0f} Hz\n"
            f"Requested polling fs: {self.requested_fs:.0f} Hz\n"
            f"High-pass cutoff: {self.highpass_cutoff:.1f} Hz"
        )

        self.sample_thread = threading.Thread(target=self.record_loop_safe)
        self.sample_thread.daemon = True
        self.sample_thread.start()

    def record_loop_safe(self):
        try:
            self.record_loop()
        except Exception as e:
            self.recording = False
            try:
                accelerometer.disable()
            except Exception:
                pass
            Clock.schedule_once(
                lambda dt, msg=str(e): self.set_status(f"Recording failed:\n{msg}"),
                0
            )

    def record_loop(self):
        start_time = time.perf_counter()
        last_ui_update = 0

        while (time.perf_counter() - start_time) < self.record_time:
            elapsed = time.perf_counter() - start_time

            accel = accelerometer.acceleration

            if accel is not None:
                ax, ay, az = accel

                if ax is not None and ay is not None and az is not None:
                    self.timestamps.append(elapsed)
                    self.ax_data.append(ax)
                    self.ay_data.append(ay)
                    self.az_data.append(az)

            if elapsed - last_ui_update > 0.5:
                last_ui_update = elapsed
                Clock.schedule_once(
                    lambda dt, e=elapsed: self.update_recording_status(e),
                    0
                )

            time.sleep(self.requested_dt)

        accelerometer.disable()
        self.recording = False

        Clock.schedule_once(lambda dt: self.finish_recording_message(), 0)

    def set_status(self, text):
        self.status.text = text

    def update_recording_status(self, elapsed):
        self.status.text = (
            f"Recording... {elapsed:.1f} / {self.record_time:.1f} s\n"
            f"Samples: {len(self.timestamps)}"
        )

    def finish_recording_message(self):
        self.status.text = f"Recording complete. Samples: {len(self.timestamps)}"

    def calculate_velocity_fft(self, accel_signal, fs):
        accel_signal = accel_signal - np.mean(accel_signal)

        n = len(accel_signal)
        window = np.hanning(n)
        coherent_gain = np.sum(window) / n

        accel_windowed = accel_signal * window

        accel_fft = np.fft.rfft(accel_windowed)
        freqs = np.fft.rfftfreq(n, d=1 / fs)

        velocity_fft = np.zeros_like(accel_fft, dtype=complex)

        valid = freqs >= self.highpass_cutoff
        velocity_fft[valid] = accel_fft[valid] / (1j * 2 * np.pi * freqs[valid])

        amplitude = np.abs(velocity_fft) / (n * coherent_gain)

        if len(amplitude) > 2:
            amplitude[1:-1] *= 2

        amplitude_mm_s = amplitude * 1000
        amplitude_mm_s[freqs < self.highpass_cutoff] = 0

        return freqs, amplitude_mm_s

    def create_fft(self, instance):
        try:
            self._create_fft()
        except Exception as e:
            self.status.text = f"FFT failed:\n{e}"

    def _create_fft(self):
        if self.recording:
            self.status.text = "Still recording. Wait until recording is complete."
            return

        if len(self.timestamps) < 20:
            self.status.text = "Not enough data. Record first."
            return

        measurement_name = safe_filename(self.name_input.text)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_prefix = f"{measurement_name}_{timestamp}"

        t_raw = np.array(self.timestamps)
        ax_raw = np.array(self.ax_data)
        ay_raw = np.array(self.ay_data)
        az_raw = np.array(self.az_data)

        dt_raw = np.diff(t_raw)
        achieved_fs = 1 / np.mean(dt_raw)
        max_gap = np.max(dt_raw)

        resample_fs = min(self.target_fs, achieved_fs * 0.8)

        if self.highpass_cutoff >= resample_fs / 2:
            self.status.text = "High-pass cutoff is too high for sample rate."
            return

        unique_t, unique_indices = np.unique(t_raw, return_index=True)

        t_raw = unique_t
        ax_raw = ax_raw[unique_indices]
        ay_raw = ay_raw[unique_indices]
        az_raw = az_raw[unique_indices]

        t_uniform = np.arange(0, t_raw[-1], 1 / resample_fs)

        ax_uniform = np.interp(t_uniform, t_raw, ax_raw)
        ay_uniform = np.interp(t_uniform, t_raw, ay_raw)
        az_uniform = np.interp(t_uniform, t_raw, az_raw)

        freq_x, amp_x = self.calculate_velocity_fft(ax_uniform, resample_fs)
        freq_y, amp_y = self.calculate_velocity_fft(ay_uniform, resample_fs)
        freq_z, amp_z = self.calculate_velocity_fft(az_uniform, resample_fs)

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        self.save_spectrum(
            f"{file_prefix}_FFT_X.png",
            freq_x,
            amp_x,
            "X-axis Velocity Spectrum",
            achieved_fs,
            resample_fs,
            max_gap
        )

        self.save_spectrum(
            f"{file_prefix}_FFT_Y.png",
            freq_y,
            amp_y,
            "Y-axis Velocity Spectrum",
            achieved_fs,
            resample_fs,
            max_gap
        )

        self.save_spectrum(
            f"{file_prefix}_FFT_Z.png",
            freq_z,
            amp_z,
            "Z-axis Velocity Spectrum",
            achieved_fs,
            resample_fs,
            max_gap
        )

        self.status.text = (
            "FFT complete.\n"
            f"Recording length: {self.record_time:.1f} s\n"
            f"Actual average sample rate: {achieved_fs:.1f} Hz\n"
            f"FFT resample rate: {resample_fs:.1f} Hz\n"
            f"High-pass cutoff: {self.highpass_cutoff:.1f} Hz\n"
            f"Saved as:\n{file_prefix}_FFT_X/Y/Z.png"
        )

    def save_spectrum(self, filename, freqs, amp, title, achieved_fs, resample_fs, max_gap):
        filepath = os.path.join(OUTPUT_FOLDER, filename)

        plt.figure()
        plt.plot(freqs, amp)
        plt.title(
            f"{title}\n"
            f"Actual fs={achieved_fs:.1f} Hz, "
            f"FFT fs={resample_fs:.1f} Hz, "
            f"HP={self.highpass_cutoff:.1f} Hz, "
            f"max dt={max_gap * 1000:.1f} ms"
        )
        plt.xlabel("Frequency / Hz")
        plt.ylabel("Velocity amplitude / mm/s peak")
        plt.grid(True)
        plt.xlim(left=self.highpass_cutoff)
        plt.savefig(filepath, dpi=150)
        plt.close()


PocketVibrationFFT().run()
