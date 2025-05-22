import os
import time
import threading
import queue
import re
import numpy as np
from scipy import signal as sig
from rtlsdr import RtlSdr
# import pyttsx3 # No longer using pyttsx3
import json
import subprocess # For OS-level TTS
import platform   # To detect OS
import shlex      # For quoting command arguments safely

# --- 1. Configuration ---
SDR_CENTER_FREQ = 145.570e6
SDR_SAMPLE_RATE = 1.024e6
SDR_GAIN = 6
SDR_NUM_SAMPLES_PER_CHUNK = 16384
RF_OFFSET = 0 # Offset tuning disabled

NFM_FILTER_CUTOFF = 4000
AUDIO_DOWNSAMPLE_RATE = 16000
STT_ENGINE = "vosk"
VOSK_MODEL_PATH = "vosk-model-small-en-us-0.15"
BASELINE_DURATION_SECONDS = 3
RF_VAD_STD_MULTIPLIER = 3.5
VAD_SPEECH_CAPTURE_SECONDS = 10.0
VAD_MAX_SPEECH_SAMPLES = int(VAD_SPEECH_CAPTURE_SECONDS * AUDIO_DOWNSAMPLE_RATE)
VAD_MIN_SPEECH_SAMPLES = int(0.75 * AUDIO_DOWNSAMPLE_RATE)
SMALL_AUDIO_CHUNK_SAMPLES = int(SDR_NUM_SAMPLES_PER_CHUNK / (SDR_SAMPLE_RATE / AUDIO_DOWNSAMPLE_RATE))
SMALL_AUDIO_CHUNK_DURATION = SMALL_AUDIO_CHUNK_SAMPLES / AUDIO_DOWNSAMPLE_RATE if AUDIO_DOWNSAMPLE_RATE > 0 else 0.016
RF_VAD_SILENCE_TO_END_SECONDS = 1.0
RF_VAD_SILENCE_CHUNKS_FOR_END = int(RF_VAD_SILENCE_TO_END_SECONDS / SMALL_AUDIO_CHUNK_DURATION) if SMALL_AUDIO_CHUNK_DURATION > 0 else 60

is_baselining_rf = True
baseline_rf_power_values = []
dynamic_rf_vad_trigger_threshold = 0.0

TRIGGER_PHRASE_END = "signal report"
NATO_PHONETIC_ALPHABET = {
    'alfa': 'a', 'bravo': 'b', 'charlie': 'c', 'delta': 'd', 'echo': 'e',
    'foxtrot': 'f', 'golf': 'g', 'hotel': 'h', 'india': 'i', 'juliett': 'j',
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

VOSK_VOCABULARY = list(NATO_PHONETIC_ALPHABET.keys()) + [str(i) for i in range(10)] + ["signal", "report"]
VOSK_GRAMMAR_STR = json.dumps(list(set(VOSK_VOCABULARY)))

audio_iq_data_queue = queue.Queue()

vosk_model = None
try:
    from vosk import Model, KaldiRecognizer
    if os.path.exists(VOSK_MODEL_PATH): vosk_model = Model(VOSK_MODEL_PATH)
    else: print(f"ERROR: Vosk model path not found: {VOSK_MODEL_PATH}")
except ImportError: print("ERROR: Vosk library not installed.")
except Exception as e: print(f"Error loading Vosk model: {e}")

def speak_and_transmit(text_to_speak):
    """Speaks text using OS-level TTS commands via subprocess."""
    print(f"TTS (subprocess): Attempting to speak: '{text_to_speak}'")
    current_os = platform.system().lower()
    cmd = []
    success = False
    command_executed = False
    # subprocess_kwargs for stdout and stderr handling
    subprocess_kwargs = {
        'text': True,
        'check': False, # We check returncode manually
        'timeout': 20   # 20s timeout for speech
    }

    try:
        if "windows" in current_os:
            escaped_text = text_to_speak.replace("'", "''") # Basic escape for PowerShell single quotes
            ps_script = (
                f"Add-Type -AssemblyName System.Speech; "
                f"$speak = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                f"$speak.Rate = 0; "
                f"$speak.Speak('{escaped_text}');"
            )
            import base64
            encoded_ps_command = base64.b64encode(ps_script.encode('utf-16-le')).decode('ascii')
            cmd = ['powershell',
                   '-NoProfile',         # Don't load profile
                   '-NonInteractive',    # Run non-interactively
                   '-ExecutionPolicy', 'Bypass',
                   '-EncodedCommand', encoded_ps_command]
            
            # For Windows, redirect PowerShell's stdout to DEVNULL to suppress execution policy messages etc.
            # Still capture stderr to see actual errors from the speech script.
            subprocess_kwargs['stdout'] = subprocess.DEVNULL
            subprocess_kwargs['stderr'] = subprocess.PIPE

        elif "darwin" in current_os: # macOS
            cmd = ['say', '-r', '180', '--', text_to_speak]
            # For macOS and Linux, capture both stdout and stderr for debugging on error
            subprocess_kwargs['capture_output'] = True
        elif "linux" in current_os:
            try:
                subprocess.run(['spd-say', '--version'], capture_output=True, text=True, check=True, timeout=2)
                cmd = ['spd-say', '-r', '-10', '-w', '--', text_to_speak]
            except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                print("TTS (subprocess): spd-say not found or failed, trying espeak...")
                try:
                    subprocess.run(['espeak', '--version'], capture_output=True, text=True, check=True, timeout=2)
                    cmd = ['espeak', '-s', '150', '--', text_to_speak]
                except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
                    print("TTS (subprocess) ERROR: Neither spd-say nor espeak found/working. Cannot speak.")
                    return
            # For macOS and Linux, capture both stdout and stderr for debugging on error
            subprocess_kwargs['capture_output'] = True
        else:
            print(f"TTS (subprocess) ERROR: Unsupported OS for TTS: {current_os}")
            return

        if cmd:
            print(f"TTS (subprocess): Executing: {' '.join(map(shlex.quote, cmd))}")
            process_result = subprocess.run(cmd, **subprocess_kwargs)
            command_executed = True
            if process_result.returncode == 0:
                print(f"TTS (subprocess): Speech command successful for: '{text_to_speak}'")
                success = True
            else:
                print(f"TTS (subprocess) ERROR: Command failed with code {process_result.returncode}")
                # process_result.stderr will be None if stderr was not piped (e.g. if changed for DEVNULL too)
                # With current kwargs, stderr IS piped for Windows, and capture_output=True pipes both for others.
                if process_result.stderr:
                    print(f"TTS (subprocess) stderr: {process_result.stderr.strip()}")
                # Only print stdout if it was captured (i.e., not for Windows in this setup if it went to DEVNULL)
                if hasattr(process_result, 'stdout') and process_result.stdout: 
                    print(f"TTS (subprocess) stdout (on error): {process_result.stdout.strip()}")
    
    except subprocess.TimeoutExpired:
        print(f"TTS (subprocess) ERROR: Speech command timed out for: '{text_to_speak}'")
    except FileNotFoundError:
        missing_cmd = cmd[0] if cmd else "TTS executable"
        print(f"TTS (subprocess) ERROR: {missing_cmd} not found. Please ensure it's installed and in PATH.")
    except Exception as e:
        print(f"TTS (subprocess) ERROR: An unexpected error occurred during speech: {e}")
        import traceback
        traceback.print_exc()

    if command_executed and success:
        print(f"Transmission complete (via OS command for: '{text_to_speak}')")
    elif command_executed and not success:
        print(f"Transmission failed or had errors (via OS command for: '{text_to_speak}')")


def sdr_callback(samples, sdr_instance):
    try:
        current_samples_shifted = samples
        chunk_rf_power = np.mean(np.abs(current_samples_shifted)**2)
        angle = np.unwrap(np.angle(current_samples_shifted))
        demodulated_signal = np.diff(angle, prepend=angle[0])
        cutoff_norm = NFM_FILTER_CUTOFF / (SDR_SAMPLE_RATE / 2.0)
        if cutoff_norm >= 1.0: cutoff_norm = 0.999
        b, a = sig.butter(8, cutoff_norm, btype='low', analog=False)
        audio_filtered = sig.lfilter(b, a, demodulated_signal)
        decimation_factor = int(SDR_SAMPLE_RATE / AUDIO_DOWNSAMPLE_RATE)
        if decimation_factor < 1: decimation_factor = 1
        num_resampled_points = int(len(audio_filtered) / decimation_factor)
        if num_resampled_points <= 0: return
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
    s9_dbfs_level = -62
    if power_dbfs > s9_dbfs_level:
        s9_plus_db_raw = power_dbfs - s9_dbfs_level
        s9_plus_db_value = int(round(s9_plus_db_raw))
        if s9_plus_db_value > 0: closest_s_unit = f"S9 plus {s9_plus_db_value} dB"
        else: closest_s_unit = "S9"
    return closest_s_unit

def calculate_signal_metrics(iq_samples_list):
    if not iq_samples_list: return "Unknown", 0.0
    try:
        full_iq_segment = np.concatenate(iq_samples_list)
        if len(full_iq_segment) == 0: return "Unknown", 0.0
        signal_plus_noise_power = np.mean(np.abs(full_iq_segment)**2)
        if signal_plus_noise_power < 1e-12: return "S0", 0.0
        signal_plus_noise_dbfs = 10 * np.log10(signal_plus_noise_power)
        snr_db = 15.0
        s_meter_reading = estimate_s_meter(signal_plus_noise_dbfs)
        return s_meter_reading, snr_db
    except Exception as e: print(f"Error calculating signal metrics: {e}"); return "Unknown", 0.0

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

def process_stt_result(text_input, iq_data_for_snr_list):
    text_lower = text_input.lower(); print(f"STT recognized: '{text_input}'")
    if text_lower.endswith(TRIGGER_PHRASE_END):
        try:
            words = text_lower.split(); nato_callsign_words = []
            for word in words:
                if word == "signal": break
                nato_callsign_words.append(word)
            if not nato_callsign_words: print("PSR: No callsign words found.")
            else:
                actual_callsign_text = convert_nato_to_text(nato_callsign_words).upper()
                if validate_callsign_format(actual_callsign_text):
                    print(f"Valid callsign format: {actual_callsign_text}"); current_time = time.time()
                    if hasattr(process_stt_result, 'last_call_info') and \
                       process_stt_result.last_call_info['callsign'] == actual_callsign_text and \
                       (current_time - process_stt_result.last_call_info['time']) < 10:
                        print(f"Callsign {actual_callsign_text} processed recently. Skipping.")
                    else:
                        process_stt_result.last_call_info = {'callsign': actual_callsign_text, 'time': current_time}
                        s_meter, snr = calculate_signal_metrics(iq_data_for_snr_list)
                        response_text = f"{actual_callsign_text}, Your signal is {s_meter} with an SNR of {snr:.1f} dB."
                        print(f"Response: {response_text}")
                        speak_and_transmit(response_text)
                else: print(f"Invalid callsign format for '{actual_callsign_text}'")
        except Exception as e: print(f"Error processing command: {e}"); import traceback; traceback.print_exc()

if not hasattr(process_stt_result, 'last_call_info'):
    process_stt_result.last_call_info = {'callsign':"", 'time':0}

def audio_processing_thread_func():
    global is_baselining_rf, baseline_rf_power_values, dynamic_rf_vad_trigger_threshold
    print("Audio processing thread started.")
    vad_audio_buffer = np.array([], dtype=np.float32); vad_iq_buffer = []
    is_capturing_speech_rf = False; rf_silence_chunk_counter = 0
    baselining_start_time = time.time()
    vosk_recognizer_instance = None
    if STT_ENGINE == "vosk" and vosk_model:
        try:
            vosk_recognizer_instance = KaldiRecognizer(vosk_model, AUDIO_DOWNSAMPLE_RATE, VOSK_GRAMMAR_STR)
            print("Vosk KaldiRecognizer initialized.")
        except Exception as e: print(f"Error initializing Vosk KaldiRecognizer: {e}"); vosk_recognizer_instance = None
    while True:
        try:
            audio_chunk_normalized, chunk_rf_power, iq_data_for_chunk = audio_iq_data_queue.get(timeout=0.1)
            if is_baselining_rf:
                baseline_rf_power_values.append(chunk_rf_power)
                if (time.time() - baselining_start_time) >= BASELINE_DURATION_SECONDS:
                    if baseline_rf_power_values:
                        avg_rf_noise = np.mean(baseline_rf_power_values); std_rf_noise = np.std(baseline_rf_power_values)
                        dynamic_rf_vad_trigger_threshold = avg_rf_noise + (RF_VAD_STD_MULTIPLIER * std_rf_noise)
                        if dynamic_rf_vad_trigger_threshold < avg_rf_noise * 1.2 : dynamic_rf_vad_trigger_threshold = avg_rf_noise * 1.2
                        if dynamic_rf_vad_trigger_threshold == 0 and avg_rf_noise == 0 : dynamic_rf_vad_trigger_threshold = 1e-9
                        print(f"--- RF Baselining complete. Threshold: {dynamic_rf_vad_trigger_threshold:.8f} ---")
                    else: print("Warning: No RF data for baselining. Using default."); dynamic_rf_vad_trigger_threshold = 1e-7 
                    is_baselining_rf = False; baseline_rf_power_values.clear()
                continue
            if is_capturing_speech_rf:
                vad_audio_buffer = np.concatenate((vad_audio_buffer, audio_chunk_normalized))
                if iq_data_for_chunk is not None: vad_iq_buffer.append(iq_data_for_chunk)
                if chunk_rf_power < dynamic_rf_vad_trigger_threshold: rf_silence_chunk_counter += 1
                else: rf_silence_chunk_counter = 0
                process_this_rf_segment = False
                if rf_silence_chunk_counter >= RF_VAD_SILENCE_CHUNKS_FOR_END:
                    print(f"VAD: End of transmission detected."); process_this_rf_segment = True
                elif len(vad_audio_buffer) >= VAD_MAX_SPEECH_SAMPLES:
                    print(f"VAD: Max speech duration reached."); process_this_rf_segment = True
                if process_this_rf_segment:
                    recognized_text_segment = None
                    if len(vad_audio_buffer) >= VAD_MIN_SPEECH_SAMPLES:
                        audio_data_int16 = (vad_audio_buffer * 32767).astype(np.int16); audio_bytes = audio_data_int16.tobytes()
                        if vosk_recognizer_instance:
                            if vosk_recognizer_instance.AcceptWaveform(audio_bytes): result = json.loads(vosk_recognizer_instance.Result()); recognized_text_segment = result.get('text', '')
                            else: final_result_json = json.loads(vosk_recognizer_instance.FinalResult()); recognized_text_segment = final_result_json.get('text', '')
                            if not recognized_text_segment: print("STT: Speech not recognized.")
                        else: print("STT: Recognizer not available.")
                        if recognized_text_segment: process_stt_result(recognized_text_segment, list(vad_iq_buffer))
                    vad_audio_buffer = np.array([], dtype=np.float32); vad_iq_buffer.clear()
                    is_capturing_speech_rf = False; rf_silence_chunk_counter = 0
                    if vosk_recognizer_instance: vosk_recognizer_instance.Reset()
            elif not is_baselining_rf and chunk_rf_power >= dynamic_rf_vad_trigger_threshold:
                print(f"VAD: Triggered! Starting capture.")
                is_capturing_speech_rf = True; vad_audio_buffer = np.copy(audio_chunk_normalized); vad_iq_buffer.clear()
                if iq_data_for_chunk is not None: vad_iq_buffer.append(iq_data_for_chunk)
                rf_silence_chunk_counter = 0
                if vosk_recognizer_instance: vosk_recognizer_instance.Reset()
        except queue.Empty: continue
        except Exception as e: print(f"Error in audio processing thread: {e}"); import traceback; traceback.print_exc()

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

if __name__ == "__main__":
    sdr = None; audio_thread = None; input_thread = None
    
    if vosk_model: print(f"Vosk model loaded: {VOSK_MODEL_PATH}")
    else: print("WARNING: Vosk model not loaded.")
    
    print(f"Radio Signal Reporter started: {time.ctime()}")
    print("INFO: RF Offset tuning feature has been removed. SDR tunes directly to center frequency.")

    try:
        print("Initializing SDR..."); sdr = RtlSdr()
        sdr.center_freq = SDR_CENTER_FREQ 
        sdr.sample_rate = SDR_SAMPLE_RATE; sdr.gain = SDR_GAIN
        print(f"SDR Configured: Freq={sdr.center_freq/1e6:.3f}MHz, Rate={sdr.sample_rate/1e6:.3f}Msps, Gain={sdr.get_gain()}dB")
        
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