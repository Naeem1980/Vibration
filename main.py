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
DEFAULT_AVERAGES = 1
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
        self.recordings = []
        self.recording = False
        self.sample_thread = None

        layout = BoxLayout(orientation="vertical", padding=10, spacing=8)

        self.status = Label(
            text=(
                "Pocket vibration estimator\n"
                f"Max recommended FFT sample rate: {MAX_RECOMMENDED_TARGET_FS} Hz\n"
                "Output: averaged velocity spectrum in mm/s peak"
            )
        )

        self.name_input = TextInput(text="Measurement", multiline=False)
        self.fs_input = TextInput(text=str(DEFAULT_TARGET_FS), multiline=False, input_filter="float")
        self.cutoff_input = TextInput(text=str(DEFAULT_HIGHPASS_CUTOFF), multiline=False, input_filter="float")
        self.record_time_input = TextInput(text=str(DEFAULT_RECORD_TIME), multiline=False, input_filter="float")
        self.average_input = TextInput(text=str(DEFAULT_AVERAGES), multiline=False, input_filter="int")

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
        layout.add_widget(Label(text="Number of recordings to average"))
        layout.add_widget(self.average_input)
        layout.add_widget(self.start_button)
        layout.add_widget(self.fft_button)

        return layout

    def start_recording(self, instance):
        if self.recording:
            self.status.text = "Already recording."
            return

        try:
            self.target_fs = float(self.fs_input.text)
            self.highpass_cutoff = float(self.cutoff_input.text)
            self.record_time = float(self.record_time_input.text)
            self.number_of_averages = int(self.average_input.text)
        except Exception as e:
            self.status.text = f"Invalid input:\n{e}"
            return

        self.target_fs = min(self.target_fs, MAX_RECOMMENDED_TARGET_FS)
        self.highpass_cutoff = max(self.highpass_cutoff, 0.1)
        self.record_time = max(self.record_time, 1.0)
        self.number_of_averages = max(self.number_of_averages, 1)

        self.requested_fs = estimate_requested_fs(self.target_fs)
        self.requested_dt = 1 / self.requested_fs

        self.recordings = []
        self.recording = True

        self.sample_thread = threading.Thread(target=self.recording_sequence_safe)
        self.sample_thread.daemon = True
        self.sample_thread.start()

    def recording_sequence_safe(self):
        try:
            self.recording_sequence()
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

    def recording_sequence(self):
        accelerometer.enable()

        for rec_no in range(1, self.number_of_averages + 1):
            timestamps = []
            ax_data = []
            ay_data = []
            az_data = []

            start_time = time.perf_counter()
            last_ui_update = 0

            Clock.schedule_once(
                lambda dt, n=rec_no: self.set_status(
                    f"Recording {n} of {self.number_of_averages}..."
                ),
                0
            )

            while (time.perf_counter() - start_time) < self.record_time:
                elapsed = time.perf_counter() - start_time
                accel = accelerometer.acceleration

                if accel is not None:
                    ax, ay, az = accel
                    if ax is not None and ay is not None and az is not None:
                        timestamps.append(elapsed)
                        ax_data.append(ax)
                        ay_data.append(ay)
                        az_data.append(az)

                if elapsed - last_ui_update > 0.5:
                    last_ui_update = elapsed
                    Clock.schedule_once(
                        lambda dt, e=elapsed, n=rec_no, s=len(timestamps):
                        self.update_recording_status(e, n, s),
                        0
                    )

                time.sleep(self.requested_dt)

            self.recordings.append({
                "t": np.array(timestamps, dtype=float),
                "x": np.array(ax_data, dtype=float),
                "y": np.array(ay_data, dtype=float),
                "z": np.array(az_data, dtype=float),
            })

            time.sleep(0.25)

        accelerometer.disable()
        self.recording = False

        Clock.schedule_once(
            lambda dt: self.set_status(
                f"Recording complete.\n"
                f"Recordings collected: {len(self.recordings)}\n"
                f"Press CREATE FFT."
            ),
            0
        )

    def set_status(self, text):
        self.status.text = text

    def update_recording_status(self, elapsed, recording_number, sample_count):
        self.status.text = (
            f"Recording {recording_number} of {self.number_of_averages}\n"
            f"{elapsed:.1f} / {self.record_time:.1f} s\n"
            f"Samples: {sample_count}"
        )

    def calculate_velocity_fft(self, accel_signal, fs):
        accel_signal = accel_signal - np.mean(accel_signal)
        n = len(accel_signal)

        window = np.hanning(n)
        coherent_gain = np.sum(window) / n

        accel_fft = np.fft.rfft(accel_signal * window)
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

        if len(self.recordings) < 1:
            self.status.text = "No recordings found. Record first."
            return

        measurement_name = safe_filename(self.name_input.text)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_prefix = f"{measurement_name}_{timestamp}"

        all_amp_x = []
        all_amp_y = []
        all_amp_z = []

        achieved_fs_list = []
        max_gap_list = []
        resample_fs_list = []

        reference_freqs = None

        for rec in self.recordings:
            t_raw = rec["t"]
            ax_raw = rec["x"]
            ay_raw = rec["y"]
            az_raw = rec["z"]

            if len(t_raw) < 20:
                continue

            dt_raw = np.diff(t_raw)
            achieved_fs = 1 / np.mean(dt_raw)
            max_gap = np.max(dt_raw)

            resample_fs = min(self.target_fs, achieved_fs * 0.8)

            if self.highpass_cutoff >= resample_fs / 2:
                self.status.text = "High-pass cutoff too high for sample rate."
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

            fx, axamp = self.calculate_velocity_fft(ax_uniform, resample_fs)
            fy, ayamp = self.calculate_velocity_fft(ay_uniform, resample_fs)
            fz, azamp = self.calculate_velocity_fft(az_uniform, resample_fs)

            if reference_freqs is None:
                reference_freqs = fx

            all_amp_x.append(np.interp(reference_freqs, fx, axamp))
            all_amp_y.append(np.interp(reference_freqs, fy, ayamp))
            all_amp_z.append(np.interp(reference_freqs, fz, azamp))

            achieved_fs_list.append(achieved_fs)
            max_gap_list.append(max_gap)
            resample_fs_list.append(resample_fs)

        if len(all_amp_x) < 1:
            self.status.text = "No valid recordings for FFT."
            return

        avg_amp_x = np.mean(np.array(all_amp_x), axis=0)
        avg_amp_y = np.mean(np.array(all_amp_y), axis=0)
        avg_amp_z = np.mean(np.array(all_amp_z), axis=0)

        avg_achieved_fs = float(np.mean(achieved_fs_list))
        avg_resample_fs = float(np.mean(resample_fs_list))
        max_gap = float(np.max(max_gap_list))

        os.makedirs(OUTPUT_FOLDER, exist_ok=True)

        self.save_spectrum(f"{file_prefix}_FFT_X.png", reference_freqs, avg_amp_x, "X-axis Velocity Spectrum", avg_achieved_fs, avg_resample_fs, max_gap)
        self.save_spectrum(f"{file_prefix}_FFT_Y.png", reference_freqs, avg_amp_y, "Y-axis Velocity Spectrum", avg_achieved_fs, avg_resample_fs, max_gap)
        self.save_spectrum(f"{file_prefix}_FFT_Z.png", reference_freqs, avg_amp_z, "Z-axis Velocity Spectrum", avg_achieved_fs, avg_resample_fs, max_gap)

        self.status.text = (
            "FFT complete.\n"
            f"Recordings averaged: {len(all_amp_x)}\n"
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
