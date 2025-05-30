import os
import time
import threading
import queue
import re
import numpy as np
from scipy import signal as sig
from rtlsdr import RtlSdr
import json
import subprocess
import platform
import shlex
from vosk import Model, KaldiRecognizer, SetLogLevel
from scipy.io import wavfile
import uuid
import matplotlib.pyplot as plt
import warnings
import requests
import xml.etree.ElementTree as ET
import datetime
from dotenv import load_dotenv

warnings.filterwarnings("ignore", message="Starting a Matplotlib GUI outside of the main thread will likely fail.")
load_dotenv()

# --- Globals and Config ---
baseline_noise_power = None
baseline_ctcss_powers = []
SetLogLevel(1)

STATION_CALLSIGN = "KR4DTT"
CONFIG_PATH = 'config.json'
AUDIO_WAV_OUTPUT_DIR = "wavs"
SAVE_SPECTROGRAM = True

CTCSS_FREQ = 100.0
CTCSS_HOLDTIME = 0.7
MIN_TRANSMISSION_LENGTH = 0.5

SDR_CENTER_FREQ = 145570000
SDR_SAMPLE_RATE = 1024000
SDR_GAIN = 0
SDR_OFFSET_TUNING = True

NFM_FILTER_CUTOFF = 4000
AUDIO_DOWNSAMPLE_RATE = 16000
HPF_CUTOFF_HZ = 150
HPF_ORDER = 4

STT_ENGINE = "vosk"
VOSK_MODEL_PATH = "vosk-model-en-us-0.22-lgraph"
BASELINE_DURATION_SECONDS = 10
SDR_NUM_SAMPLES_PER_CHUNK = 16384

TRIGGER_PHRASE_END = "signal report"
S9_DBFS_REF = -62

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

cfg = load_config()

CTCSS_FREQ = float(cfg.get('CTCSS_FREQ', 100.0))
ctcss_threshold_cfg = cfg.get('CTCSS_THRESHOLD', 750)
if str(ctcss_threshold_cfg).lower() == 'auto':
    CTCSS_THRESHOLD = None
else:
    CTCSS_THRESHOLD = float(ctcss_threshold_cfg)
CTCSS_HOLDTIME = float(cfg.get('CTCSS_HOLDTIME', 0.7))
MIN_TRANSMISSION_LENGTH = float(cfg.get('MIN_TRANSMISSION_LENGTH', 0.5))
AUDIO_WAV_OUTPUT_DIR = "wavs"

SDR_CENTER_FREQ = float(cfg.get('SDR_CENTER_FREQ', 145570000))
if SDR_CENTER_FREQ < 1e6:
    SDR_CENTER_FREQ = SDR_CENTER_FREQ * 1e6
SDR_SAMPLE_RATE = float(cfg.get('SDR_SAMPLE_RATE', 1024000))
SDR_GAIN = int(cfg.get('SDR_GAIN', 0))
SDR_OFFSET_TUNING = bool(cfg.get('SDR_OFFSET_TUNING', True))

SAVE_SPECTROGRAM = True

NFM_FILTER_CUTOFF = 4000
AUDIO_DOWNSAMPLE_RATE = 16000
STT_ENGINE = "vosk"
VOSK_MODEL_PATH = "vosk-model-en-us-0.22-lgraph"
BASELINE_DURATION_SECONDS = 10
SDR_NUM_SAMPLES_PER_CHUNK = 16384
SMALL_AUDIO_CHUNK_SAMPLES = int(SDR_NUM_SAMPLES_PER_CHUNK / (SDR_SAMPLE_RATE / AUDIO_DOWNSAMPLE_RATE))
SMALL_AUDIO_CHUNK_DURATION = SMALL_AUDIO_CHUNK_SAMPLES / AUDIO_DOWNSAMPLE_RATE if AUDIO_DOWNSAMPLE_RATE > 0 else 0.016

is_baselining_rf = True
baseline_rf_power_values = []

RF_VAD_STD_MULTIPLIER = 1.5
VAD_SPEECH_CAPTURE_SECONDS = 10.0
VAD_MAX_SPEECH_SAMPLES = int(VAD_SPEECH_CAPTURE_SECONDS * AUDIO_DOWNSAMPLE_RATE)
VAD_MIN_SPEECH_SAMPLES = int(0.75 * AUDIO_DOWNSAMPLE_RATE)
RF_VAD_SILENCE_TO_END_SECONDS = 1.0
RF_VAD_SILENCE_CHUNKS_FOR_END = int(RF_VAD_SILENCE_TO_END_SECONDS / SMALL_AUDIO_CHUNK_DURATION) if SMALL_AUDIO_CHUNK_DURATION > 0 else 60
dynamic_rf_vad_trigger_threshold = 0.0

TRIGGER_PHRASE_END = "signal report"
NATO_PHONETIC_ALPHABET = {
    'alfa': 'a', 'bravo': 'b', 'charlie': 'c', 'delta': 'd', 'echo': 'e',
    'foxtrot': 'f', 'golf': 'g', 'hotel': 'h', 'india': 'i', 'juliet': 'j',
    'kilo': 'k', 'lima': 'l', 'mike': 'm', 'november': 'n', 'oscar': 'o',
    'papa': 'p', 'quebec': 'q', 'romeo': 'r', 'sierra': 's', 'tango': 't',
    'uniform': 'u', 'victor': 'v', 'whiskey': 'w', 'x-ray': 'x', 'yankee': 'y',
    'zulu': 'z', 'zero': '0', 'one': '1', 'two': '2', 'three': '3',
    'four': '4', 'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9'
}
CALLSIGN_REGEX = r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}[A-Z]$|^[A-Z]{2}[0-9]{1,4}[A-Z]$"
S_METER_DBFS_MAP = {
    -120: "S0", -110: "S1", -104: "S2", -98: "S3", -92: "S4", -86: "S5",
    -80: "S6", -74: "S7", -68: "S8", -62: "S9", -56: "S9+6dB", -50: "S9+12dB",
    -44: "S9+18dB", -38: "S9+24dB", -32: "S9+30dB", -26: "S9+36dB", -20: "S9+40dB"
}

S9_DBFS_REF = float(cfg.get('S9_DBFS_REF', -62))

HPF_CUTOFF_HZ = 150
HPF_ORDER = 4
HPF_SOS = sig.butter(
    HPF_ORDER,
    HPF_CUTOFF_HZ / (AUDIO_DOWNSAMPLE_RATE / 2),
    btype='highpass',
    output='sos'
)

# --- Vosk Grammar Setup ---
VOSK_VOCABULARY = []
if STT_ENGINE == "vosk":
    VOSK_VOCABULARY.extend(list(NATO_PHONETIC_ALPHABET.keys()))
    VOSK_VOCABULARY.extend(["signal", "report"])
    VOSK_GRAMMAR_STR = json.dumps(list(set(VOSK_VOCABULARY)))
else:
    VOSK_GRAMMAR_STR = None

audio_iq_data_queue = queue.Queue()

# --- Vosk Model Load ---
vosk_model = None
try:
    from vosk import Model, KaldiRecognizer
    if os.path.exists(VOSK_MODEL_PATH):
        vosk_model = Model(VOSK_MODEL_PATH)
    else:
        print(f"ERROR: Vosk model path not found: {VOSK_MODEL_PATH}")
except ImportError:
    print("ERROR: Vosk library not installed.")
except Exception as e:
    print(f"Error loading Vosk model: {e}")

from signal_db import log_signal_report, ensure_table_exists
ensure_table_exists()

# --- TTS and Transmission ---
def speak_and_transmit(text_to_speak):
    current_os = platform.system().lower()
    cmd = []
    success = False
    command_executed = False
    subprocess_kwargs = {
        'text': True,
        'check': False,
        'timeout': 20
    }
    try:
        if "windows" in current_os:
            escaped_text = text_to_speak.replace("'", "''")
            tts_wav_path = "tts_output.wav"
            ps_script = (
                f"Add-Type -AssemblyName System.Speech; "
                f"$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$speak.SetOutputToWaveFile('{tts_wav_path}'); "
                f"$speak.Rate = 0; "
                f"$speak.Speak('{escaped_text}');"
            )
            import base64
            encoded_ps_command = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
            cmd = ['powershell',
                   '-NoProfile',
                   '-NonInteractive',
                   '-ExecutionPolicy', 'Bypass',
                   '-EncodedCommand', encoded_ps_command]
            subprocess_kwargs['stdout'] = subprocess.DEVNULL
            subprocess_kwargs['stderr'] = subprocess.PIPE
        elif "darwin" in current_os:
            cmd = ['say', '-r', '180', '--', text_to_speak]
            subprocess_kwargs['capture_output'] = True
        elif "linux" in current_os:
            try:
                subprocess.run(['spd-say', '--version'], capture_output=True, text=True, check=True, timeout=2)
                cmd = ['spd-say', '-r', '-10', '-w', '--', text_to_speak]
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                try:
                    subprocess.run(['espeak', '--version'], capture_output=True, text=True, check=True, timeout=2)
                    tts_wav_path = "tts_output.wav"
                    cmd = ['espeak', '-s', '150', '-w', tts_wav_path, '--', text_to_speak]
                except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    print("TTS ERROR: Neither spd-say nor espeak found/working.")
                    return
            subprocess_kwargs['capture_output'] = True
        else:
            print(f"TTS ERROR: Unsupported OS for TTS: {current_os}")
            return

        if cmd:
            process_result = subprocess.run(cmd, **subprocess_kwargs)
            command_executed = True
            if process_result.returncode == 0:
                success = True
            else:
                print(f"TTS ERROR: Command failed (code {process_result.returncode})")
                if process_result.stderr:
                    print(f"TTS stderr: {process_result.stderr.strip()}")
                if hasattr(process_result, 'stdout') and process_result.stdout:
                    print(f"TTS stdout (on error): {process_result.stdout.strip()}")

    except subprocess.TimeoutExpired:
        print(f"TTS ERROR: Speech command timed out.")
    except FileNotFoundError:
        missing_cmd = cmd[0] if cmd else "TTS executable"
        print(f"TTS ERROR: {missing_cmd} not found. Please ensure it's installed and in PATH.")
    except Exception as e:
        print(f"TTS ERROR: An unexpected error occurred during speech: {e}")
        import traceback
        traceback.print_exc()

    rate, data = wavfile.read(tts_wav_path)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / 32767.0
    data_with_tone = mix_ultrasonic_tone(data, rate)
    wavfile.write(tts_wav_path, rate, (data_with_tone * 32767).astype(np.int16))
    if "windows" in current_os:
        play_cmd = [
            "powershell",
            "-c",
            f"(New-Object Media.SoundPlayer '{tts_wav_path}').PlaySync();"
        ]
        subprocess.run(play_cmd)
    elif "darwin" in current_os:
        subprocess.run(["afplay", tts_wav_path])
    elif "linux" in current_os:
        try:
            subprocess.run(["aplay", tts_wav_path])
        except FileNotFoundError:
            subprocess.run(["paplay", tts_wav_path])
    else:
        print("No supported audio playback method for this OS.")
    print(f"Transmitted: '{text_to_speak}'")

# --- SDR Callback ---
def sdr_callback(samples, sdr_instance):
    try:
        current_samples_shifted = samples
        chunk_rf_power = np.mean(np.abs(current_samples_shifted)**2)
        angle = np.unwrap(np.angle(current_samples_shifted))
        demodulated_signal = np.diff(angle, prepend=angle[0])
        cutoff_norm = NFM_FILTER_CUTOFF / (SDR_SAMPLE_RATE / 2.0)
        if (cutoff_norm >= 1.0): cutoff_norm = 0.999
        b, a = sig.butter(8, cutoff_norm, btype='low', analog=False)
        audio_filtered = sig.lfilter(b, a, demodulated_signal)
        decimation_factor = int(SDR_SAMPLE_RATE / AUDIO_DOWNSAMPLE_RATE)
        if (decimation_factor < 1): decimation_factor = 1
        num_resampled_points = int(len(audio_filtered) / decimation_factor)
        if (num_resampled_points <= 0): return
        audio_resampled = sig.resample(audio_filtered, num_resampled_points)
        max_abs_val = np.max(np.abs(audio_resampled))
        audio_normalized = (audio_resampled / max_abs_val * 0.8) if max_abs_val > 1e-9 else audio_resampled
        audio_iq_data_queue.put((audio_normalized, chunk_rf_power, np.copy(current_samples_shifted)))
    except Exception as e:
        print(f"Error in sdr_callback: {e}")

# --- Signal Metrics ---
def estimate_s_meter(power_dbfs):
    if power_dbfs is None: return "Unknown"
    closest_s_unit = "S0"; s_map_sorted = sorted(S_METER_DBFS_MAP.items())
    for dbfs_level, s_unit_val in s_map_sorted:
        if power_dbfs >= dbfs_level: closest_s_unit = s_unit_val
        else: break
    s9_dbfs_level = S9_DBFS_REF
    if power_dbfs > s9_dbfs_level:
        s9_plus_db_raw = power_dbfs - s9_dbfs_level
        s9_plus_db_value = int(round(s9_plus_db_raw))
        if s9_plus_db_value > 0: closest_s_unit = f"S9 plus {s9_plus_db_value} dB"
        else: closest_s_unit = "S9"
    return closest_s_unit

def calculate_signal_metrics(iq_samples_list):
    global baseline_noise_power
    if not iq_samples_list:
        return "Unknown", 0.0
    try:
        full_iq_segment = np.concatenate(iq_samples_list)
        if len(full_iq_segment) == 0:
            return "Unknown", 0.0
        signal_plus_noise_power = np.mean(np.abs(full_iq_segment)**2)
        if signal_plus_noise_power < 1e-12:
            return "S0", 0.0
        signal_plus_noise_dbfs = 10 * np.log10(signal_plus_noise_power)
        if baseline_noise_power and baseline_noise_power > 0:
            noise_power = baseline_noise_power
        else:
            n = len(full_iq_segment)
            edge = max(1, n // 10)
            noise_samples = np.concatenate([full_iq_segment[:edge], full_iq_segment[-edge:]])
            noise_power = np.median(np.abs(noise_samples)**2)
            if noise_power < 1e-12:
                noise_power = 1e-12
        noise_dbfs = 10 * np.log10(noise_power)
        snr_linear = (signal_plus_noise_power - noise_power) / noise_power
        snr_db = 10 * np.log10(max(snr_linear, 1e-12))
        s_meter_reading = estimate_s_meter(signal_plus_noise_dbfs)
        print(f"signal+noise: {signal_plus_noise_power}, noise: {noise_power}, snr_linear: {snr_linear}, snr_db: {snr_db}")
        return s_meter_reading, snr_db
    except Exception as e:
        print(f"Error calculating signal metrics: {e}")
        return "Unknown", 0.0

# --- Callsign and STT Processing ---
def convert_nato_to_text(nato_words_from_stt):
    callsign_chars = []
    for word in nato_words_from_stt:
        word_lower = word.lower()
        if word_lower in NATO_PHONETIC_ALPHABET: callsign_chars.append(NATO_PHONETIC_ALPHABET[word_lower])
        elif word_lower.isdigit() and len(word_lower) == 1: callsign_chars.append(word_lower)
    return "".join(callsign_chars)

def validate_callsign_format(callsign_text):
    if not callsign_text: return False
    return bool(re.match(CALLSIGN_REGEX, callsign_text.upper()))

def process_stt_result(text_input, iq_data_for_snr_list, uid=None, audio_path=None, spectrogram_path=None):
    text_lower = text_input.lower(); print(f"STT recognized: '{text_input}'")
    try:
        words = text_lower.split(); nato_callsign_words = []
        for word in words:
            if word == "signal": break
            nato_callsign_words.append(word)
        actual_callsign_text = convert_nato_to_text(nato_callsign_words).upper() if nato_callsign_words else ''
        current_time = time.time()
        s_meter, snr = calculate_signal_metrics(iq_data_for_snr_list)
        duration_sec = getattr(process_stt_result, 'last_audio_len', 0) / AUDIO_DOWNSAMPLE_RATE
        log_callsign = actual_callsign_text if validate_callsign_format(actual_callsign_text) else 'Unknown'
        log_signal_report(
            log_callsign, s_meter, snr, text_input, duration_sec,
            audio_path, spectrogram_path
        )
        if text_lower.endswith(TRIGGER_PHRASE_END) and validate_callsign_format(actual_callsign_text):
            if hasattr(process_stt_result, 'last_call_info') and \
               process_stt_result.last_call_info['callsign'] == actual_callsign_text and \
               (current_time - process_stt_result.last_call_info['time']) < 10:
                print(f"Callsign {actual_callsign_text} processed recently. Skipping response.")
            else:
                process_stt_result.last_call_info = {'callsign': actual_callsign_text, 'time': current_time}
                response_text = f"{actual_callsign_text}, your signal is {s_meter}, SNR {int(round(snr))} dB."
                print(f"Response: {response_text}")
                speak_and_transmit(response_text)
        elif not validate_callsign_format(actual_callsign_text):
            print(f"Invalid or missing callsign for '{actual_callsign_text}', logged as 'Unknown'.")
    except Exception as e:
        print(f"Error processing command: {e}"); import traceback; traceback.print_exc()

if not hasattr(process_stt_result, 'last_call_info'):
    process_stt_result.last_call_info = {'callsign':"", 'time':0}

SIGREP_STATUS_FILE = 'sigrep_status.json'

def write_status(state):
    if state == 'ready':
        status = {'state': state, 'last_started': time.strftime('%Y-%m-%d %H:%M:%S')}
    else:
        status = {'state': state}
    with open(SIGREP_STATUS_FILE, 'w') as f:
        json.dump(status, f)

write_status('initializing')

ID_INTERVAL_SECONDS = 600
last_id_time = time.time()

# --- Main Audio Processing Thread ---
def audio_processing_thread_func():
    global is_baselining_rf, baseline_rf_power_values
    global dtmf_last_digit, dtmf_last_time, dtmf_buffer
    global parrot_mode, parrot_recording, parrot_audio, parrot_waiting_for_next_transmission, parrot_ready_to_record
    global CTCSS_THRESHOLD
    global last_id_time

    print("Audio processing thread started.")
    write_status('baselining')
    audio_buffer = np.array([], dtype=np.float32)
    iq_buffer = []
    ctcss_buffer = np.array([], dtype=np.float32)
    ctcss_active = False
    last_ctcss_time = 0
    baselining_start_time = time.time()
    vosk_recognizer_instance = None

    if STT_ENGINE == "vosk" and vosk_model:
        try:
            vosk_recognizer_instance = KaldiRecognizer(vosk_model, AUDIO_DOWNSAMPLE_RATE, VOSK_GRAMMAR_STR)
            print("Vosk KaldiRecognizer initialized.")
            print("RF Baselining in progress... Please wait for baseline to complete before transmitting signal.")
        except Exception as e:
            print(f"Error initializing Vosk KaldiRecognizer: {e}")
            vosk_recognizer_instance = None

    baseline_ctcss_buffer = np.array([], dtype=np.float32)
    ctcss_consecutive_count = 0
    CTCSS_CONSECUTIVE_REQUIRED = 8

    while True:
        try:
            # --- Automatic Station ID ---
            if time.time() - last_id_time > ID_INTERVAL_SECONDS:
                speak_and_transmit(f"This is {STATION_CALLSIGN} repeater.")
                last_id_time = time.time()

            audio_chunk_normalized, chunk_rf_power, iq_data_for_chunk = audio_iq_data_queue.get(timeout=0.1)
            current_time = time.time()

            dtmf_digit = detect_dtmf_digit(audio_chunk_normalized, AUDIO_DOWNSAMPLE_RATE)
            if dtmf_digit:
                now = time.time()
                if dtmf_digit != dtmf_last_digit or (now - dtmf_last_time) > DTMF_DEBOUNCE_TIME:
                    print(f"DTMF detected: {dtmf_digit}")
                    dtmf_buffer += dtmf_digit
                    dtmf_last_digit = dtmf_digit
                    dtmf_last_time = now

                # --- DTMF Command Handling ---
                if dtmf_buffer.endswith("#91"):
                    now = datetime.datetime.now()
                    time_str = now.strftime("%I:%M %p").lstrip("0")
                    speak_and_transmit(f"The current time is {time_str}.")
                    dtmf_buffer = ""
                    dtmf_last_digit = None
                    dtmf_last_time = 0

                if dtmf_buffer.endswith("#92"):
                    now = datetime.datetime.now()
                    date_str = now.strftime("%A, %B %d, %Y")
                    speak_and_transmit(f"Today is {date_str}.")
                    dtmf_buffer = ""
                    dtmf_last_digit = None
                    dtmf_last_time = 0

                match = re.search(r"#93(\d{5})", dtmf_buffer)
                if match:
                    zip_code = match.group(1)
                    print(f"Weather request triggered by DTMF #93{zip_code}.")
                    speak_and_transmit("Weather request received. Please wait.")
                    weather = get_weather_for_zip(zip_code)
                    speak_and_transmit(weather)
                    dtmf_buffer = ""
                    dtmf_last_digit = None
                    dtmf_last_time = 0

                if dtmf_buffer.endswith("#95"):
                    last_call = getattr(process_stt_result, 'last_call_info', None)
                    if last_call and last_call.get('callsign'):
                        s_meter = last_call.get('s_meter', 'Unknown')
                        snr = last_call.get('snr', 0)
                        callsign = last_call.get('callsign', 'Unknown')
                        speak_and_transmit(f"Last signal was {callsign}, S meter {s_meter}, SNR {int(round(snr))} dB.")
                    else:
                        speak_and_transmit("No recent signal report available.")
                    dtmf_buffer = ""
                    dtmf_last_digit = None
                    dtmf_last_time = 0

                if dtmf_buffer.endswith("#98"):
                    print("Parrot mode enabled by DTMF #98.")
                    parrot_mode = True
                    parrot_waiting_for_next_vad = True
                    dtmf_buffer = ""
                    dtmf_last_digit = None
                    dtmf_last_time = 0

            if dtmf_buffer.endswith("#94"):
                print("HF band conditions requested by DTMF #94.")
                band_report = get_hamqsl_hf_band_conditions()
                speak_and_transmit(band_report)
                dtmf_buffer = ""
                dtmf_last_digit = None
                dtmf_last_time = 0

            if dtmf_buffer.endswith("#43"):
                print("Help requested by DTMF #43.")
                help_text = (
                    "Available commands are: "
                    "Pound Nine one for current time. "
                    "Pound Nine two for current date. "
                    "Pound Nine three followed by zip code for weather. "
                    "Pound Nine four for HF band conditions. "
                    "Pound Nine five for last signal report. "
                    "Pound Nine eight for parrot mode. "
                    "Pound Four three for this help message."
                )
                speak_and_transmit(help_text)
                dtmf_buffer = ""
                dtmf_last_digit = None
                dtmf_last_time = 0

            # --- Baselining ---
            if is_baselining_rf:
                baseline_rf_power_values.append(chunk_rf_power)
                baseline_ctcss_buffer = np.concatenate((baseline_ctcss_buffer, audio_chunk_normalized))
                if len(baseline_ctcss_buffer) >= 2048:
                    ctcss_power = detect_ctcss_tone(baseline_ctcss_buffer, AUDIO_DOWNSAMPLE_RATE, return_power=True)
                    print(f"Baseline CTCSS power: {ctcss_power}")
                    baseline_ctcss_powers.append(ctcss_power)
                    baseline_ctcss_buffer = np.array([], dtype=np.float32)
                if (time.time() - baselining_start_time) >= BASELINE_DURATION_SECONDS:
                    if baseline_rf_power_values:
                        avg_rf_noise = np.mean(baseline_rf_power_values)
                        std_rf_noise = np.std(baseline_rf_power_values)
                        baseline_noise_power = avg_rf_noise
                    is_baselining_rf = False
                    baseline_rf_power_values.clear()
                    max_baseline_ctcss_power = max(baseline_ctcss_powers) if baseline_ctcss_powers else 0
                    if str(cfg.get('CTCSS_THRESHOLD', 'auto')).lower() == 'auto':
                        CTCSS_THRESHOLD = max_baseline_ctcss_power * 2.1
                        if not CTCSS_THRESHOLD or CTCSS_THRESHOLD < 1:
                            CTCSS_THRESHOLD = 1000
                        print(f"Auto CTCSS threshold set to {CTCSS_THRESHOLD:.2f} (2.1x max baseline CTCSS power {max_baseline_ctcss_power:.2f})")
                        print(f"Baseline noise power set to: {baseline_noise_power}")
                    else:
                        CTCSS_THRESHOLD = float(cfg.get('CTCSS_THRESHOLD'))
                        print(f"Manual CTCSS threshold set to {CTCSS_THRESHOLD:.2f}")
                    baseline_ctcss_powers.clear()
                    write_status('ready')
                    ctcss_buffer = np.array([], dtype=np.float32)
                    ctcss_consecutive_count = 0
                    ctcss_active = False
                    last_ctcss_time = current_time
                    continue

            # --- CTCSS Detection ---
            ctcss_buffer = np.concatenate((ctcss_buffer, audio_chunk_normalized))
            ctcss_detected = False
            if len(ctcss_buffer) >= 2048 and CTCSS_THRESHOLD is not None:
                ctcss_power = detect_ctcss_tone(ctcss_buffer, AUDIO_DOWNSAMPLE_RATE, return_power=True)
                ctcss_detected = ctcss_power > CTCSS_THRESHOLD
                ctcss_buffer = np.array([], dtype=np.float32)

                if ctcss_detected:
                    ctcss_consecutive_count += 1
                else:
                    ctcss_consecutive_count = 0

                if ctcss_consecutive_count >= CTCSS_CONSECUTIVE_REQUIRED:
                    last_ctcss_time = current_time
                    if not ctcss_active:
                        print("CTCSS detected: starting capture.")
                        ctcss_active = True

            if ctcss_active or ctcss_detected or (current_time - last_ctcss_time) <= CTCSS_HOLDTIME:
                audio_buffer = np.concatenate((audio_buffer, audio_chunk_normalized))
                if iq_data_for_chunk is not None:
                    iq_buffer.append(iq_data_for_chunk)

            if ctcss_detected:
                last_ctcss_time = current_time
                if not ctcss_active:
                    print("CTCSS detected: starting capture.")
                    ctcss_active = True

            # --- End of CTCSS, process segment ---
            if ctcss_active and (current_time - last_ctcss_time) > CTCSS_HOLDTIME:
                buffer_duration = len(audio_buffer) / AUDIO_DOWNSAMPLE_RATE
                print(f"CTCSS lost: processing segment ({buffer_duration:.2f}s audio).")
                if buffer_duration >= MIN_TRANSMISSION_LENGTH:
                    os.makedirs(AUDIO_WAV_OUTPUT_DIR, exist_ok=True)
                    capture_uid = uuid.uuid4().hex[:16]
                    wav_filename = f"ctcss_capture_{time.strftime('%Y%m%d_%H%M%S')}_{capture_uid}.wav"
                    wav_path = os.path.join(AUDIO_WAV_OUTPUT_DIR, wav_filename)
                    audio_for_wav = sig.sosfilt(HPF_SOS, audio_buffer)
                    audio_data_int16 = np.clip(audio_for_wav, -1.0, 1.0) * 32767
                    audio_data_int16 = audio_data_int16.astype(np.int16)
                    wavfile.write(wav_path, AUDIO_DOWNSAMPLE_RATE, audio_data_int16)

                    # --- Save Spectrogram ---
                    if SAVE_SPECTROGRAM:
                        spec_filename = wav_filename.replace('.wav', '.png')
                        spec_path = os.path.join(AUDIO_WAV_OUTPUT_DIR, spec_filename)
                        plt.figure(figsize=(8, 4))
                        plt.specgram(audio_for_wav, NFFT=256, Fs=AUDIO_DOWNSAMPLE_RATE, noverlap=128, cmap='viridis')
                        plt.title(f"Spectrogram {capture_uid}")
                        plt.xlabel("Time (s)")
                        plt.ylabel("Frequency (Hz)")
                        plt.colorbar(label="Intensity (dB)")
                        plt.savefig(spec_path, bbox_inches='tight')
                        plt.close()

                    # --- Speech-to-Text (STT) Processing ---
                    if not parrot_mode:
                        recognized_text_segment = ''
                        if vosk_recognizer_instance:
                            audio_bytes = audio_data_int16.tobytes()
                            vosk_recognizer_instance.Reset()
                            if vosk_recognizer_instance.AcceptWaveform(audio_bytes):
                                result = json.loads(vosk_recognizer_instance.Result())
                                recognized_text_segment = result.get('text', '')
                            else:
                                final_result_json = json.loads(vosk_recognizer_instance.FinalResult())
                                recognized_text_segment = final_result_json.get('text', '')
                            print(f"STT recognized: '{recognized_text_segment}'")
                        else:
                            print("STT: Recognizer not available.")

                        process_stt_result.last_audio_len = len(audio_buffer)
                        process_stt_result(
                            recognized_text_segment or '',
                            list(iq_buffer),
                            uid=capture_uid,
                            audio_path=wav_path,
                            spectrogram_path=spec_path if SAVE_SPECTROGRAM else None
                        )

                audio_buffer = np.array([], dtype=np.float32)
                iq_buffer.clear()
                ctcss_active = False

        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error in audio processing thread: {e}")
            import traceback
            traceback.print_exc()

        # --- Parrot Mode ---
        if parrot_mode and parrot_waiting_for_next_vad and not ctcss_active:
            print("Parrot mode enabled. Please transmit a phrase.")
            speak_and_transmit("Parrot mode enabled. Please transmit a phrase.")
            parrot_waiting_for_next_vad = False
            parrot_ready_to_record = True

        if parrot_mode and parrot_ready_to_record:
            if ctcss_active:
                parrot_recording = True
                parrot_ready_to_record = False
                parrot_audio = []
                print("Parrot mode: Recording transmission...")

        if parrot_mode and parrot_recording and ctcss_active:
            parrot_audio.append(np.copy(audio_chunk_normalized))

        if parrot_mode and parrot_recording and len(parrot_audio) > 0 and not ctcss_active:
            print("Playing back your transmission...")
            speak_and_transmit("Playing back your transmission.")
            parrot_samples = np.concatenate(parrot_audio)
            parrot_wav_path = os.path.join(AUDIO_WAV_OUTPUT_DIR, "parrot_playback.wav")
            wavfile.write(parrot_wav_path, AUDIO_DOWNSAMPLE_RATE, (parrot_samples * 32767).astype(np.int16))
            current_os = platform.system().lower()
            if "windows" in current_os:
                play_cmd = [
                    "powershell",
                    "-c",
                    f"(New-Object Media.SoundPlayer '{parrot_wav_path}').PlaySync();"
                ]
                subprocess.run(play_cmd)
            elif "darwin" in current_os:
                subprocess.run(["afplay", parrot_wav_path])
            elif "linux" in current_os:
                try:
                    subprocess.run(["aplay", parrot_wav_path])
                except FileNotFoundError:
                    subprocess.run(["paplay", parrot_wav_path])
            parrot_mode = False
            parrot_recording = False
            parrot_audio = []
            parrot_waiting_for_next_vad = False
            parrot_ready_to_record = False

# --- Input Monitor Thread ---
def input_monitor_thread_func():
    print("Input monitor thread started. Type 'exit' to quit.")
    while True:
        try:
            command = input()
            if command.strip().lower() == 'exit':
                print("Exit command received. Shutting down...")
                if sdr: print("Stopping SDR..."); sdr.cancel_read_async(); sdr.close(); print("SDR closed.")
                print("Exiting script."); os._exit(0)
        except EOFError: print("EOF on input, exiting."); os._exit(0)
        except Exception as e: print(f"Input monitor error: {e}, exiting."); os._exit(0)

# --- Utility: Mix Ultrasonic Tone ---
def mix_ultrasonic_tone(audio, sample_rate, tone_freq=18000, tone_level=0.01):
    t = np.arange(len(audio)) / sample_rate
    tone = tone_level * np.sin(2 * np.pi * tone_freq * t)
    return audio + tone

# --- DTMF Detection ---
DTMF_FREQS = {
    'low': [697, 770, 852, 941],
    'high': [1209, 1336, 1477, 1633]
}
DTMF_MAP = {
    (697, 1209): '1', (697, 1336): '2', (697, 1477): '3',
    (770, 1209): '4', (770, 1336): '5', (770, 1477): '6',
    (852, 1209): '7', (852, 1336): '8', (852, 1477): '9',
    (941, 1209): '*', (941, 1336): '0', (941, 1477): '#'
}
DTMF_DEBOUNCE_TIME = 0.35

dtmf_last_digit = None
dtmf_last_time = 0
dtmf_buffer = ""
parrot_mode = False
parrot_recording = False
parrot_audio = []
parrot_waiting_for_next_vad = False
parrot_ready_to_record = False

def get_weather_for_zip(zip_code):
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    url = f"http://api.openweathermap.org/data/2.5/weather?zip={zip_code},us&appid={api_key}&units=imperial"
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if "main" in data and "weather" in data and "name" in data:
            temp = data["main"].get("temp")
            desc = data["weather"][0].get("description", "").capitalize()
            temp_min = data["main"].get("temp_min")
            temp_max = data["main"].get("temp_max")
            city = data.get("name", "your area")
            humidity = data["main"].get("humidity")
            wind = data.get("wind", {}).get("speed")
            report = f"The current temperature in {city} is {int(round(temp))} degrees, {desc}."
            if temp_max is not None and temp_min is not None:
                report += f" The high is {int(round(temp_max))} and the low is {int(round(temp_min))} degrees."
            if humidity is not None:
                report += f" Humidity is {humidity} percent."
            if wind is not None:
                report += f" Wind speed is {int(round(wind))} miles per hour."
            return report
        elif "message" in data:
            return f"Sorry, weather API error: {data['message']}"
        else:
            return "Sorry, I could not find the weather for that zip code."
    except Exception as e:
        return "Sorry, there was an error retrieving the weather."

def detect_dtmf_digit(samples, sample_rate):
    def goertzel(samples, freq, sample_rate):
        N = len(samples)
        k = int(0.5 + N * freq / sample_rate)
        w = 2 * np.pi * k / N
        cosine = np.cos(w)
        coeff = 2 * cosine
        q0 = 0
        q1 = 0
        q2 = 0
        for sample in samples:
            q0 = coeff * q1 - q2 + sample
            q2 = q1
            q1 = q0
        return q1**2 + q2**2 - q1*q2*coeff

    low_strengths = {f: goertzel(samples, f, sample_rate) for f in DTMF_FREQS['low']}
    high_strengths = {f: goertzel(samples, f, sample_rate) for f in DTMF_FREQS['high']}
    low = max(low_strengths, key=low_strengths.get)
    high = max(high_strengths, key=high_strengths.get)
    low_val = low_strengths[low]
    high_val = high_strengths[high]
    low_sorted = sorted(low_strengths.values(), reverse=True)
    high_sorted = sorted(high_strengths.values(), reverse=True)
    MIN_POWER = 1000
    DOMINANCE = 3.0
    BAND_BALANCE = 0.5
    if low_val < MIN_POWER or high_val < MIN_POWER:
        return None
    if low_sorted[1] > (low_val / DOMINANCE):
        return None
    if high_sorted[1] > (high_val / DOMINANCE):
        return None
    ratio = min(low_val, high_val) / max(low_val, high_val)
    if ratio < BAND_BALANCE:
        return None
    return DTMF_MAP.get((low, high))

def detect_ctcss_tone(audio_samples, sample_rate, ctcss_freq=CTCSS_FREQ, threshold=None, return_power=False):
    N = len(audio_samples)
    if N < int(sample_rate * 0.02):
        return (0.0 if return_power else False)
    k = int(0.5 + N * ctcss_freq / sample_rate)
    w = 2 * np.pi * k / N
    cosine = np.cos(w)
    coeff = 2 * cosine
    q0 = 0
    q1 = 0
    q2 = 0
    for sample in audio_samples:
        q0 = coeff * q1 - q2 + sample
        q2 = q1
        q1 = q0
    power = q1**2 + q2**2 - q1*q2*coeff
    if return_power:
        return power
    if threshold is None:
        threshold = CTCSS_THRESHOLD if CTCSS_THRESHOLD is not None else 1000
    return power > threshold

def get_hamqsl_hf_band_conditions():
    url = "https://www.hamqsl.com/solarxml.php"
    try:
        resp = requests.get(url, timeout=5)
        root = ET.fromstring(resp.content)
        bands = {}
        spoken_lines = []
        for band_elem in root.findall(".//calculatedconditions/band"):
            name = band_elem.attrib.get("name")
            time = band_elem.attrib.get("time")
            cond = band_elem.text.strip()
            if name not in bands:
                bands[name] = {}
            bands[name][time] = cond
        for band in ["80m-40m", "30m-20m", "17m-15m", "12m-10m"]:
            day = bands.get(band, {}).get("day", "unknown")
            night = bands.get(band, {}).get("night", "unknown")
            band_spoken = band.replace("m-", " meter to ").replace("m", " meter")
            spoken_lines.append(f"{band_spoken} daytime {day.lower()} night time {night.lower()}")
        return ". ".join(spoken_lines)
    except Exception as e:
        print(f"Error fetching HF band conditions: {e}")
        return "Sorry, I could not retrieve HF band conditions."

# --- Main Entrypoint ---
if __name__ == "__main__":
    sdr = None; audio_thread = None; input_thread = None
    if vosk_model: print(f"Vosk model loaded: {VOSK_MODEL_PATH}")
    else: print("WARNING: Vosk model not loaded.")
    print(f"Signal Reporter started: {time.ctime()}")
    try:
        print("Initializing SDR..."); sdr = RtlSdr()
        sdr.center_freq = SDR_CENTER_FREQ
        sdr.sample_rate = SDR_SAMPLE_RATE; sdr.gain = SDR_GAIN
        sdr.offset_tuning = SDR_OFFSET_TUNING
        print(f"SDR Configured: Freq={sdr.center_freq/1e6:.3f}MHz, Rate={sdr.sample_rate/1e6:.3f}Msps, Gain={sdr.get_gain()}dB, OffsetTuning={sdr.offset_tuning}")
        audio_thread = threading.Thread(target=audio_processing_thread_func, daemon=True); audio_thread.start()
        input_thread = threading.Thread(target=input_monitor_thread_func, daemon=True); input_thread.start()
        print(f"Performing {BASELINE_DURATION_SECONDS}s RF baselining...")
        print(f"Listening on {SDR_CENTER_FREQ/1e6:.3f} MHz for '{TRIGGER_PHRASE_END}'...")
        sdr.read_samples_async(sdr_callback, num_samples=SDR_NUM_SAMPLES_PER_CHUNK)
        while True:
            time.sleep(1)
            if audio_thread and not audio_thread.is_alive():
                print("ERROR: Audio processing thread died. Exiting."); os._exit(1)
    except KeyboardInterrupt: print("\nCtrl+C. Shutting down...");
    except Exception as e: print(f"Main loop error: {e}"); import traceback; traceback.print_exc()
    finally:
        print("Main: Initiating final shutdown...")
        if sdr: sdr.cancel_read_async(); sdr.close()
        print("Shutdown complete.")