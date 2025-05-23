# OpenSignalReport - Automated Amateur Radio Signal Reporter

## Project Overview

OpenSignalReport is a Python-based application designed to automate the process of providing signal reports to amateur radio operators. It utilizes a Software Defined Radio (SDR) to listen on a designated amateur radio frequency for voice transmissions. When a user transmits their callsign (using the NATO phonetic alphabet) followed by the phrase "signal report," the system processes this command and aims to respond.

The core idea is to enable a PC running this script to interact with standard analog handheld transceivers (HTs) or other analog radios. The script uses an offline Speech-to-Text (STT) engine (Vosk) with a custom vocabulary to transcribe the incoming voice command. If successful, it analyzes the received radio transmission to estimate signal metrics like S-meter reading and Signal-to-Noise Ratio (SNR). A voice response is then generated using OS-level Text-to-Speech (TTS).

Crucially, for transmitting this voice response back to the user, the system is designed to interface with an analog radio via a specialized audio interface cable, such as the **APRS-K1 PRO cable (or similar)**. These cables typically handle automatic Push-to-Talk (PTT) activation when they detect audio output from the PC's sound card, allowing the script's TTS response to be broadcast over the air.

The project logs successful reports to a CSV file and can optionally save captured audio and spectrograms for analysis, serving as an experimental tool and utility for the amateur radio community.

## Features

* **RF Power Based Voice Activity Detection (VAD):** Dynamically establishes a noise baseline and triggers on significant increases in RF power.
* **Offset Tuning for SDR:** Helps mitigate DC spike/center-frequency artifacts from SDRs.
* **Offline Speech-to-Text:** Uses the Vosk STT engine with a customizable vocabulary for recognizing callsigns (NATO phonetic) and commands.
* **Automated Signal Metrics:** Provides estimated S-meter and SNR reports.
* **Text-to-Speech (TTS) Response:** Uses OS-level TTS commands for generating voice responses.
* **Interface for Analog Radio Transmission:** Designed for use with audio-triggered PTT interface cables (e.g., [APRS-K1 PRO from BaofengTech](https://baofengtech.com/product/aprs-k1-pro) or similar) to transmit responses back to analog HTs.
* **Logging:**
    * General activity logging via Python's `logging` module (to console and file).
    * Successful signal reports logged to a CSV file.
* **Diagnostics (Optional):**
    * Ability to save VAD-captured audio segments as WAV files.
    * Ability to save spectrograms of captured audio.
* **Configurable:** Key parameters like frequency, gain, VAD thresholds, and STT model paths are configurable.
* **Graceful Exit:** Supports exiting via Ctrl+C or by typing "exit" in the console.

## Prerequisites

* Python 3.7+
* An RTL-SDR dongle (e.g., RTL-SDR Blog V4) or compatible SDR supported by `pyrtlsdr`.
* An appropriate antenna for the target listening frequency (e.g., 2-meter band).
* Vosk Speech Recognition Toolkit:
    * Python library: `pip install vosk`
    * A downloaded Vosk language model (e.g., `vosk-model-en-us-0.22-lgraph`).
### Optional Prerequisites
* **An audio interface cable for transmission,** such as the [APRS-K1 PRO](https://baofengtech.com/product/aprs-k1-pro) or a similar cable that supports audio input to your transmitter and features automatic PTT/VOX based on audio from the PC's sound card output.
* A transmitting analog radio (e.g., a Baofeng HT or other VHF/UHF transceiver) compatible with the interface cable.


## Installation

1.  **Install Python dependencies:**
    ```bash
    pip install numpy scipy rtlsdr SpeechRecognition vosk soundfile matplotlib
    ```
    * `SpeechRecognition` is still useful for `sr.AudioData` objects if using Google STT as a fallback, and for its microphone class if you were to adapt the script for direct mic input.
    * `soundfile` and `matplotlib` are needed if you enable VAD WAV saving and spectrogram generation.

2.  **Download a Vosk Language Model:**
    * Go to the [Vosk Models Page](https://alphacephei.com/vosk/models).
    * Download a suitable English model (e.g., `vosk-model-en-us-0.22-lgraph` is recommended for better accuracy).
    * Extract the model folder and place it in a known location. Update `VOSK_MODEL_PATH` in the script.

## Configuration

Open the Python script (`.py` file) and modify the constants in the "Configuration" section near the top:

* **SDR Settings:**
    * `SDR_CENTER_FREQ`: Your desired listening frequency. **Find a quiet simplex frequency in your area!**
    * `SDR_SAMPLE_RATE`: Typically `1.024e6` or `2.048e6`.
    * `SDR_GAIN`: SDR RF gain in dB. **Start with a value known to work for your SDR (e.g., >= 6dB, try 15.7-36.4dB).** Tune this for best audio quality vs. noise.
    * `RF_OFFSET`: Set to `int(SDR_SAMPLE_RATE / 4)` to enable offset tuning (recommended). Set to `0` to disable.
* **VAD Configuration:**
    * `BASELINE_DURATION_SECONDS`: How long to listen to establish the noise floor (e.g., `15`).
    * `RF_VAD_STD_MULTIPLIER`: **Critical tuning parameter.** How many standard deviations above the average baseline RF power to trigger VAD (e.g., `3.0` to `5.0`).
    * `VAD_SPEECH_CAPTURE_SECONDS`: Maximum duration to record once VAD triggers (e.g., `10.0`).
    * `RF_VAD_SILENCE_TO_END_SECONDS`: How much RF silence (below threshold) ends a VAD capture early.
* **STT Configuration:**
    * `STT_ENGINE`: Set to `"vosk"`.
    * `VOSK_MODEL_PATH`: Path to your downloaded Vosk model folder.
* **Logging & Diagnostics:**
    * `GENERAL_LOG_FILENAME`, `REPORT_CSV_FILENAME`, `VAD_WAV_OUTPUT_DIR`, `SAVE_SPECTROGRAM`.
* **Callsign and Phrase:**
    * `TRIGGER_PHRASE_END`: Currently `"signal report"`.

## Transmission Setup & Audio Levels

* **Connect Cable:** Connect your APRS-K1 PRO (or similar) cable between your PC's sound output (speaker/headphone jack) and your analog HT's microphone/speaker port.
* **PC Audio Output:** Ensure the correct PC audio output device is selected as the default for system sounds or for the Python application if possible.
* **VOLUME ADJUSTMENT (CRITICAL):**
    1.  Set your **transmitting radio's microphone gain** to a mid-to-low level initially.
    2.  Set your **PC's system output volume** to a low-to-mid level.
    3.  When the script transmits, listen on a separate receiver.
    4.  Gradually adjust the **PC's output volume** until the APRS cable's Auto PTT reliably keys your radio and the transmitted audio is clear, undistorted, and at an appropriate modulation level. Avoid overdriving the radio's mic input.
* **Mute PC Notifications:** Disable or mute system notification sounds on your PC to prevent accidental transmission.

## Running the Script

1.  Ensure SDR and audio interface/radio are connected.
2.  Navigate to the script's directory.
3.  Run: `python your_script_name.py`
4.  The script will perform RF power baselining. **Ensure the frequency is clear of strong signals and your own transmissions during this period.**
5.  After baselining, it will listen. Transmit your callsign (NATO phonetic) followed by "signal report".
6.  To exit: type `exit` in the console and press Enter, or press `Ctrl+C`.

## Tuning and Troubleshooting

* **VAD Not Triggering / Triggering on Noise:**
    * Check `Average Baseline RF Power` and `Dynamic RF VAD Trigger Threshold`. If threshold is too high, baseline noise was high (RFI, gain too high). Find quieter frequency/reduce gain.
    * If VAD doesn't trigger on speech, your speech RF power might be too low (increase `SDR_GAIN` slightly, ensure clear transmission) or `RF_VAD_STD_MULTIPLIER` might be too high.
    * If VAD triggers on noise, increase `RF_VAD_STD_MULTIPLIER`.
* **STT Failures ("Speech not recognized"):**
    * Enable VAD WAV saving. Listen to the saved files. Is your voice clear?
    * Adjust `SDR_GAIN` to optimize *demodulated audio quality*.
    * Ensure clear, deliberate speech into your radio.
    * Use the largest Vosk model your system can handle.
* **No Transmission or Distorted Transmission:**
    * Check PC audio output levels and radio mic gain carefully (see "Transmission Setup").
    * Ensure the APRS-K1 PRO cable is functioning and its Auto PTT is triggering.

## Future Possible Functionality
* More precise SNR/S-meter calculations.
* Web interface/dashboard.
* Database logging (e.g., SQLite).
* Support for more voice commands.
* Interference detection.
* Support for other modes (CW, PSK).

## Disclaimer

This software is for experimental and educational purposes. Always operate in accordance with your amateur radio license privileges and local regulations. The control operator is responsible for all transmissions made by this automated system.

---
