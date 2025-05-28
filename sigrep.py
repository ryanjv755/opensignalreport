import os
import time
import threading
import queue
import re
import numpy as np
from scipy import signal as sig
from rtlsdr import RtlSdr
import json
import subprocess # For OS-level TTS
import platform   # To detect OS
import shlex      # For quoting command arguments safely
from vosk import Model, KaldiRecognizer, SetLogLevel # Import SetLogLevel
from scipy.io import wavfile
import uuid
import matplotlib.pyplot as plt  # At the top of your script
import warnings
import sqlite3  # Add for SQLite logging
warnings.filterwarnings("ignore", message="Starting a Matplotlib GUI outside of the main thread will likely fail.")

# Add at the top of your script
baseline_noise_power = None
baseline_ctcss_powers = []

# --- Set Vosk Log Level ---
# Set before initializing any Vosk objects to reduce startup verbosity
# Level 0 is default (verbose), 1 is warnings/errors, -1 is suppress all
SetLogLevel(1) # Only show warnings and errors from Vosk

# --- Configuration ---
CONFIG_PATH = 'config.json'
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

cfg = load_config()

CTCSS_FREQ = float(cfg.get('CTCSS_FREQ', 100.0))
ctcss_threshold_cfg = cfg.get('CTCSS_THRESHOLD', 750)
if str(ctcss_threshold_cfg).lower() == 'auto':
    CTCSS_THRESHOLD = None  # Will be set after baselining
else:
    CTCSS_THRESHOLD = float(ctcss_threshold_cfg)
CTCSS_HOLDTIME = float(cfg.get('CTCSS_HOLDTIME', 0.7))  # seconds, adjust as needed
MIN_TRANSMISSION_LENGTH = float(cfg.get('MIN_TRANSMISSION_LENGTH', 0.5))  # seconds, ignore very short segments
AUDIO_WAV_OUTPUT_DIR = "wavs"

SDR_CENTER_FREQ = float(cfg.get('SDR_CENTER_FREQ', 145570000))
if SDR_CENTER_FREQ < 1e6:  # If user entered in MHz (e.g. 145.570)
    SDR_CENTER_FREQ = SDR_CENTER_FREQ * 1e6
SDR_SAMPLE_RATE = float(cfg.get('SDR_SAMPLE_RATE', 1024000))
SDR_GAIN = int(cfg.get('SDR_GAIN', 0))
SDR_OFFSET_TUNING = bool(cfg.get('SDR_OFFSET_TUNING', True))

# VAD Wav output directory and spectrogram save option
VAD_WAV_OUTPUT_DIR = "wavs"
SAVE_SPECTROGRAM = True  # or from config if you wish

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

# VAD parameters
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

# S9 dBFS reference, configurable via config.json (default -62)
S9_DBFS_REF = float(cfg.get('S9_DBFS_REF', -62))

HPF_CUTOFF_HZ = 150  # High-pass filter cutoff frequency in Hz
HPF_ORDER = 4        # 4th order Butterworth

# Calculate filter coefficients globally for efficiency
HPF_SOS = sig.butter(
    HPF_ORDER,
    HPF_CUTOFF_HZ / (AUDIO_DOWNSAMPLE_RATE / 2),
    btype='highpass',
    output='sos'
)

VOSK_VOCABULARY = []
if STT_ENGINE == "vosk":

    # Add all NATO phonetic words (which includes words for numbers like "zero", "one", "four")
    VOSK_VOCABULARY.extend(list(NATO_PHONETIC_ALPHABET.keys()))
    # Add command words
    VOSK_VOCABULARY.extend(["signal", "report"])

    VOSK_GRAMMAR_STR = json.dumps(list(set(VOSK_VOCABULARY)))
else:
    VOSK_GRAMMAR_STR = None


audio_iq_data_queue = queue.Queue()

vosk_model = None
try:
    from vosk import Model, KaldiRecognizer
    if os.path.exists(VOSK_MODEL_PATH): vosk_model = Model(VOSK_MODEL_PATH)
    else: print(f"ERROR: Vosk model path not found: {VOSK_MODEL_PATH}")
except ImportError: print("ERROR: Vosk library not installed.")
except Exception as e: print(f"Error loading Vosk model: {e}")

# --- SQLite Setup ---
# (Moved to signal_db.py)
from signal_db import log_signal_report, ensure_table_exists
ensure_table_exists()

def speak_and_transmit(text_to_speak):
    """Speaks text using OS-level TTS commands via subprocess."""
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

    # Mix tone and play WAV as before (if using WAV output)
    from scipy.io import wavfile

    # Read the TTS WAV
    rate, data = wavfile.read(tts_wav_path)
    if data.dtype != np.float32:
        data = data.astype(np.float32) / 32767.0  # Convert to float32 if needed

    # Mix in the tone
    data_with_tone = mix_ultrasonic_tone(data, rate)

    # Convert back to int16 and save
    wavfile.write(tts_wav_path, rate, (data_with_tone * 32767).astype(np.int16))

    import sys

    # Play the WAV file (blocking)
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
    except Exception as e: print(f"Error in sdr_callback: {e}")

def estimate_s_meter(power_dbfs):
    if power_dbfs is None: return "Unknown"
    closest_s_unit = "S0"; s_map_sorted = sorted(S_METER_DBFS_MAP.items())
    for dbfs_level, s_unit_val in s_map_sorted:
        if power_dbfs >= dbfs_level: closest_s_unit = s_unit_val
        else: break
    # Use configurable S9 dBFS reference
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

        # Use baseline noise power if available, else fallback to old method
        if baseline_noise_power and baseline_noise_power > 0:
            noise_power = baseline_noise_power
        else:
            n = len(full_iq_segment)
            edge = max(1, n // 10)
            noise_samples = np.concatenate([full_iq_segment[:edge], full_iq_segment[-edge:]])
            noise_power = np.median(np.abs(noise_samples)**2)
            if noise_power < 1e-12:
                noise_power = 1e-12  # avoid log(0)

        noise_dbfs = 10 * np.log10(noise_power)
        snr_linear = (signal_plus_noise_power - noise_power) / noise_power
        snr_db = 10 * np.log10(max(snr_linear, 1e-12))
        snr_db = max(0.0, snr_db)

        s_meter_reading = estimate_s_meter(signal_plus_noise_dbfs)
        return s_meter_reading, snr_db
    except Exception as e:
        print(f"Error calculating signal metrics: {e}")
        return "Unknown", 0.0

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

def process_stt_result(text_input, iq_data_for_snr_list, uid=None):
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
        log_signal_report(log_callsign, s_meter, snr, text_input, duration_sec, uid=uid)
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
    # If state is 'ready', include a 'last_started' timestamp
    if state == 'ready':
        status = {'state': state, 'last_started': time.strftime('%Y-%m-%d %H:%M:%S')}
    else:
        status = {'state': state}
    with open(SIGREP_STATUS_FILE, 'w') as f:
        json.dump(status, f)

def audio_processing_thread_func():
    global is_baselining_rf, baseline_rf_power_values
    global dtmf_last_digit, dtmf_last_time, dtmf_buffer
    global parrot_mode, parrot_recording, parrot_audio, parrot_waiting_for_next_transmission, parrot_ready_to_record

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

    # --- NEW: Baseline CTCSS Buffer ---
    baseline_ctcss_buffer = np.array([], dtype=np.float32)
    ctcss_consecutive_count = 0
    CTCSS_CONSECUTIVE_REQUIRED = 3  # Tune as needed

    while True:
        try:
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

                    # --- Parrot Mode Trigger ---
                    if dtmf_buffer.endswith("#98") and not parrot_mode:
                        print("Parrot mode enabled by DTMF #98.")
                        parrot_mode = True
                        parrot_waiting_for_next_vad = True
                        dtmf_buffer = ""  # Optionally clear buffer after trigger

            # --- DTMF and Parrot Mode Activation (unchanged) ---
            # ... (keep your DTMF and parrot mode logic here) ...

            # --- RF Baselining (unchanged) ---
            if is_baselining_rf:
                baseline_rf_power_values.append(chunk_rf_power)
                # Also measure CTCSS power for this chunk
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
                    # --- NEW CTCSS THRESHOLD LOGIC ---
                    max_baseline_ctcss_power = max(baseline_ctcss_powers) if baseline_ctcss_powers else 0
                    if str(cfg.get('CTCSS_THRESHOLD', 'auto')).lower() == 'auto':
                        CTCSS_THRESHOLD = max_baseline_ctcss_power * 1.5
                        if not CTCSS_THRESHOLD or CTCSS_THRESHOLD < 1:  # Avoid zero/very low threshold
                            CTCSS_THRESHOLD = 1000  # <-- Set a safe default for your environment
                        print(f"Auto CTCSS threshold set to {CTCSS_THRESHOLD:.2f} (1.5x max baseline CTCSS power {max_baseline_ctcss_power:.2f})")
                    else:
                        CTCSS_THRESHOLD = float(cfg.get('CTCSS_THRESHOLD'))
                        print(f"Manual CTCSS threshold set to {CTCSS_THRESHOLD:.2f}")
                    baseline_ctcss_powers.clear()
                continue

            # --- CTCSS Detection and Audio Buffering ---
            ctcss_buffer = np.concatenate((ctcss_buffer, audio_chunk_normalized))
            ctcss_detected = False
            if len(ctcss_buffer) >= 2048:
                ctcss_power = detect_ctcss_tone(ctcss_buffer, AUDIO_DOWNSAMPLE_RATE, return_power=True)
                ctcss_detected = ctcss_power > CTCSS_THRESHOLD
                ctcss_buffer = np.array([], dtype=np.float32)

                if ctcss_detected:
                    ctcss_consecutive_count += 1
                else:
                    ctcss_consecutive_count = 0

                if ctcss_consecutive_count >= CTCSS_CONSECUTIVE_REQUIRED:
                    # Only now set ctcss_active = True and start capture
                    last_ctcss_time = current_time
                    if not ctcss_active:
                        print("CTCSS detected: starting capture.")
                        ctcss_active = True

            # Always buffer audio while CTCSS is active or within holdtime
            if ctcss_active or ctcss_detected or (current_time - last_ctcss_time) <= CTCSS_HOLDTIME:
                audio_buffer = np.concatenate((audio_buffer, audio_chunk_normalized))
                if iq_data_for_chunk is not None:
                    iq_buffer.append(iq_data_for_chunk)

            if ctcss_detected:
                last_ctcss_time = current_time
                if not ctcss_active:
                    print("CTCSS detected: starting capture.")
                    ctcss_active = True

            # Only end capture if CTCSS has been gone for holdtime
            if ctcss_active and (current_time - last_ctcss_time) > CTCSS_HOLDTIME:
                buffer_duration = len(audio_buffer) / AUDIO_DOWNSAMPLE_RATE
                print(f"CTCSS lost: processing segment ({buffer_duration:.2f}s audio).")
                if buffer_duration >= MIN_TRANSMISSION_LENGTH:
                    # --- Save WAV ---
                    os.makedirs(AUDIO_WAV_OUTPUT_DIR, exist_ok=True)
                    capture_uid = uuid.uuid4().hex[:16]
                    wav_filename = f"ctcss_capture_{time.strftime('%Y%m%d_%H%M%S')}_{capture_uid}.wav"
                    wav_path = os.path.join(AUDIO_WAV_OUTPUT_DIR, wav_filename)
                    # Apply HPF if you use it for STT
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

                    # --- STT Recognition ---
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

                    # --- Log the signal report ---
                    process_stt_result.last_audio_len = len(audio_buffer)
                    process_stt_result(
                        recognized_text_segment or '',
                        list(iq_buffer),
                        uid=capture_uid
                    )

                # Clear buffers after processing
                audio_buffer = np.array([], dtype=np.float32)
                iq_buffer.clear()
                ctcss_active = False

            # --- Parrot Mode Logic (unchanged) ---
            # ... (keep your parrot mode logic here) ...

        except queue.Empty:
            continue
        except Exception as e:
            print(f"Error in audio processing thread: {e}")
            import traceback
            traceback.print_exc()

        # --- Parrot Mode Logic ---
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

        #audio_processing_thread_func.was_capturing_speech_rf = is_capturing_speech_rf

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

def mix_ultrasonic_tone(audio, sample_rate, tone_freq=18000, tone_level=0.01):
    t = np.arange(len(audio)) / sample_rate
    tone = tone_level * np.sin(2 * np.pi * tone_freq * t)
    return audio + tone

# --- DTMF Detection Parameters ---
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
DTMF_DEBOUNCE_TIME = 0.35  # seconds, adjust as needed

dtmf_last_digit = None
dtmf_last_time = 0
dtmf_buffer = ""
parrot_mode = False
parrot_recording = False
parrot_audio = []
parrot_waiting_for_next_vad = False
parrot_ready_to_record = False  # <-- Add this line

def detect_dtmf_digit(samples, sample_rate):
    """Detect a single DTMF digit in the given audio samples using Goertzel algorithm with stricter validation."""
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

    # Calculate Goertzel power for all DTMF freqs
    low_strengths = {f: goertzel(samples, f, sample_rate) for f in DTMF_FREQS['low']}
    high_strengths = {f: goertzel(samples, f, sample_rate) for f in DTMF_FREQS['high']}
    low = max(low_strengths, key=low_strengths.get)
    high = max(high_strengths, key=high_strengths.get)
    low_val = low_strengths[low]
    high_val = high_strengths[high]

    # Require both bands to be strong and much stronger than the next
    low_sorted = sorted(low_strengths.values(), reverse=True)
    high_sorted = sorted(high_strengths.values(), reverse=True)

    # --- TUNE THESE THRESHOLDS ---
    MIN_POWER = 1000         # Minimum power for a valid tone (increase if needed)
    DOMINANCE = 3.0         # Strongest must be this many times stronger than next
    BAND_BALANCE = 0.5      # Low and high must be similar in power (ratio)
    # -----------------------------

    # Check minimum power
    if low_val < MIN_POWER or high_val < MIN_POWER:
        return None
    # Check dominance
    if low_sorted[1] > (low_val / DOMINANCE):
        return None
    if high_sorted[1] > (high_val / DOMINANCE):
        return None
    # Check band balance (avoid speech harmonics)
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
        threshold = CTCSS_THRESHOLD if CTCSS_THRESHOLD is not None else 1000  # fallback
    return power > threshold

if __name__ == "__main__":
    sdr = None; audio_thread = None; input_thread = None
    
    if vosk_model: print(f"Vosk model loaded: {VOSK_MODEL_PATH}")
    else: print("WARNING: Vosk model not loaded.")
    
    print(f"Signal Reporter started: {time.ctime()}")

    try:
        print("Initializing SDR..."); sdr = RtlSdr()
        sdr.center_freq = SDR_CENTER_FREQ 
        sdr.sample_rate = SDR_SAMPLE_RATE; sdr.gain = SDR_GAIN

        # Enable offset tuning to avoid DC spike at center frequency
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