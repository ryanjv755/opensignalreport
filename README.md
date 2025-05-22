# SDR Signal Reporter

This Python script listens to a specified radio frequency using an RTL-SDR dongle, detects voice activity, listens for a callsign (using NATO phonetic alphabet) followed by the trigger phrase "signal report", and responds with an S-meter reading and estimated SNR. The audio response will be played through the sound card, but can be automatically transmitted back via a connected handheld radio using a PTT-capable cable.

## Features

* **Real-time RF Processing**: Captures and demodulates NFM (Narrowband FM) signals from an RTL-SDR.
* **RF-Based Voice Activity Detection (VAD)**: Dynamically establishes a noise baseline and triggers audio recording when significant RF power is detected.
* **Speech-to-Text (STT)**: Utilizes the Vosk offline speech recognition toolkit to convert spoken audio to text.
    * **Custom Grammar**: Primarily listens for NATO phonetic alphabet words, numbers, and the phrase "signal report" for improved accuracy.
* **Callsign Recognition**:
    * Converts recognized NATO phonetic alphabet words (e.g., "Alfa Bravo One Two Charlie Delta") into a standard callsign format (e.g., "AB12CD").
    * Validates the recognized callsign against a common amateur radio callsign regex.
* **Signal Strength Reporting**:
    * Estimates S-meter reading based on received signal power (dBFS).
    * Provides a basic SNR estimation.
* **Text-to-Speech (TTS) Response with Radio Transmission**:
    * Verbally announces the signal report back to the recognized callsign.
    * Uses OS-native TTS engines for cross-platform compatibility (Windows, macOS, Linux).
    * **Designed for automatic transmission**: The audio output is intended to be routed to a handheld radio via a cable like the [BaofengTech APRS-K1 Pro](https://baofengtech.com/product/aprs-k1-pro), which handles automatic PTT (Push-To-Talk).
* **Configurable Parameters**: Easily adjust SDR settings, VAD thresholds, audio rates, and STT model path.
* **Console Output**: Provides detailed logging of its operations.

## How It Works

1.  **SDR Initialization**: Connects to an RTL-SDR dongle and tunes to the configured `SDR_CENTER_FREQ`.
2.  **RF Baselining**: For the first few seconds (`BASELINE_DURATION_SECONDS`), the script listens to establish an average RF noise floor. This is used to set a dynamic threshold for the RF-based Voice Activity Detection (VAD).
3.  **RF Monitoring & Demodulation**:
    * Continuously reads IQ samples from the SDR.
    * Demodulates the NFM signal.
    * Filters and downsamples the audio to `AUDIO_DOWNSAMPLE_RATE`.
4.  **Voice Activity Detection (VAD)**:
    * Monitors the RF power of incoming chunks.
    * If the power exceeds the `dynamic_rf_vad_trigger_threshold`, it starts capturing audio.
    * Continues capturing until RF power drops below the threshold for a set duration (`RF_VAD_SILENCE_TO_END_SECONDS`) or max duration (`VAD_SPEECH_CAPTURE_SECONDS`) is reached.
5.  **Speech-to-Text (STT)**:
    * The captured audio buffer is passed to the Vosk KaldiRecognizer.
    * Vosk transcribes the audio using the defined grammar (NATO alphabet, numbers, "signal report").
6.  **Command Processing**:
    * The script checks if the transcribed text ends with "signal report".
    * It extracts the preceding words, attempts to convert them from NATO phonetic alphabet to a callsign.
    * The callsign is validated against a regex.
7.  **Signal Metrics & Response Generation**:
    * If a valid callsign and trigger phrase are found, it calculates the S-meter reading and a nominal SNR from the captured IQ samples.
    * It constructs a response string (e.g., "AB1CD, Your signal is S9 plus 10 dB with an SNR of 15.0 dB.").
8.  **Text-to-Speech and Transmission**:
    * The `speak_and_transmit` function uses the operating system's built-in TTS capabilities to generate the audio for the response.
    * This audio output is then sent through the computer's audio out, intended to be connected to a handheld radio via a PTT-activating cable (like the APRS-K1 Pro). The cable triggers the radio's PTT, and the audio is transmitted on the radio's programmed frequency.
    * A cooldown mechanism prevents responding to the same callsign repeatedly within a short time (10 seconds).
9.  **Loop**: The process repeats from step 3.

## Requirements

* **Python 3.x**
* **RTL-SDR Dongle** and associated drivers (librtlsdr).
* **Handheld Radio** (e.g., Baofeng or similar) with a K1-type accessory jack if using the APRS-K1 Pro cable.
* **APRS-K1 Pro Cable (or similar VOX/PTT-activating cable)**:
    * Such as the [BaofengTech APRS-K1 Pro](https://baofengtech.com/product/aprs-k1-pro). This cable connects the computer's audio output/input to the radio's speaker/mic port and is designed to key the radio's PTT automatically when audio is sent from the computer.
* **Python Libraries**:
    * `rtlsdr` (pyrtlsdr)
    * `numpy`
    * `scipy`
    * `vosk`
* **Vosk Speech Recognition Model**:
    * A Vosk model compatible with the configured language (e.g., `vosk-model-small-en-us-0.15`). Download from [Vosk Models](https://alphacephei.com/vosk/models).
* **Operating System Text-to-Speech (TTS) tools**:
    * **Windows**: PowerShell (usually available by default).
    * **macOS**: `say` command (available by default).
    * **Linux**: `spd-say` (speech-dispatcher) or `espeak`. Install if not present (e.g., `sudo apt install speech-dispatcher espeak`).

## Installation

1.  **Clone the repository or download the script.**
2.  **Install Python libraries**:
    ```bash
    pip install numpy scipy pyrtlsdr vosk
    ```
3.  **Download a Vosk Model**:
    * Go to [https://alphacephei.com/vosk/models](https://alphacephei.com/vosk/models).
    * Download a suitable model (e.g., `vosk-model-small-en-us-0.15`).
    * Extract the model folder and place it in a known location.
4.  **Configure the script**:
    * Open the Python script in a text editor.
    * Update `VOSK_MODEL_PATH` to the path of your extracted Vosk model folder (e.g., `VOSK_MODEL_PATH = "path/to/your/vosk-model-small-en-us-0.15"`).
    * Adjust other parameters in the "Configuration" section of the script as needed (see below).

## Hardware Setup for Transmission

1.  **Connect the RTL-SDR dongle** to your computer. This will be used for *receiving* signals.
2.  **Connect the APRS-K1 Pro cable** (or similar PTT-activating interface cable):
    * Plug the appropriate connectors into your computer's audio output (speaker/headphone jack) and potentially an audio input (mic jack, though this script primarily uses it for PTT via audio signaling inherent to such cables or VOX on the radio if the cable only routes audio).
    * Connect the K1 connector to your handheld radio.
3.  **Configure your Handheld Radio**:
    * Set the radio to the desired *transmit* frequency. This should be different from the SDR listening frequency. For example, you might listen on a repeater output and transmit on its input, or use a simplex frequency for reception and a different simplex frequency for transmission if you are acting as a cross-band responder.
    * Ensure the radio's volume and VOX settings (if applicable and relied upon by your cable/setup) are appropriately adjusted for clear transmission triggered by the computer's audio. The APRS-K1 Pro is designed to handle PTT, but levels are still important.
4.  **Computer Audio Settings**:
    * Ensure the default audio output of your computer is routed to the jack where the APRS-K1 Pro cable is connected.
    * Adjust the output volume from your computer to an appropriate level for the radio input – not too quiet, not too loud to cause distortion. Test this carefully.

**Important Considerations for Transmission:**
* **Licensing:** Ensure you have the appropriate amateur radio license to transmit on the frequencies you configure.
* **Regulations:** Always operate in accordance_with local and national radio regulations.
* **Frequency Coordination:** Be mindful of band plans and avoid interfering with other users or services. Using a simplex repeater setup or designated frequencies for automated systems is recommended.
* **Testing:** Test your setup at low power first and get feedback on your audio quality and signal.

## Configuration

Key parameters at the top of the script:

* `SDR_CENTER_FREQ`: The frequency (in Hz) the SDR should tune to for *listening* (e.g., `145.570e6` for 145.570 MHz).
* `SDR_SAMPLE_RATE`: Sample rate for the SDR (e.g., `1.024e6`).
* `SDR_GAIN`: SDR gain in dB (e.g., `6`). Use 'auto' for automatic gain control if supported by your SDR and library version, otherwise set a specific numeric value.
* `SDR_NUM_SAMPLES_PER_CHUNK`: Number of samples to process at a time.
* `NFM_FILTER_CUTOFF`: Low-pass filter cutoff for NFM demodulation (e.g., `4000` Hz).
* `AUDIO_DOWNSAMPLE_RATE`: Audio sample rate for STT processing (e.g., `16000` Hz). Must match what the Vosk model expects or be compatible.
* `STT_ENGINE`: Currently set to "vosk".
* `VOSK_MODEL_PATH`: **Crucial!** Path to the Vosk model directory.
* `BASELINE_DURATION_SECONDS`: Duration (in seconds) for initial RF noise floor calibration.
* `RF_VAD_STD_MULTIPLIER`: Multiplier for standard deviation above average noise to set the VAD threshold.
* `VAD_SPEECH_CAPTURE_SECONDS`: Maximum duration for a single voice capture.
* `VAD_MIN_SPEECH_SAMPLES`: Minimum audio length to be considered valid speech for STT.
* `RF_VAD_SILENCE_TO_END_SECONDS`: Duration of RF silence to consider a transmission ended.
* `TRIGGER_PHRASE_END`: The phrase that must follow the callsign (e.g., `"signal report"`).
* `NATO_PHONETIC_ALPHABET`: Dictionary mapping phonetic words to characters.
* `CALLSIGN_REGEX`: Regular expression for validating recognized callsigns.

## Usage

1.  Complete the **Hardware Setup for Transmission** as described above.
2.  Ensure your RTL-SDR dongle is connected.
3.  Make sure you have installed all requirements and configured the `VOSK_MODEL_PATH`.
4.  Run the script from your terminal:
    ```bash
    python your_script_name.py
    ```
5.  The script will start, initialize the SDR, and perform RF baselining.
6.  It will then print "Listening on [frequency] MHz for 'signal report'..."
7.  When someone transmits their callsign using NATO phonetic alphabet followed by "signal report" on the tuned frequency (e.g., "Kilo One Alfa Bravo Charlie signal report"), the script will:
    * Detect the transmission.
    * Attempt to transcribe it.
    * If successful, validate the callsign.
    * Announce a signal report using TTS. This audio will be routed through the connected cable, keying the radio to transmit the response on its configured frequency. (e.g., "K1ABC, Your signal is S9 with an SNR of 15.0 dB.").
8.  To stop the script, type `exit` in the console where it's running and press Enter, or press `Ctrl+C`.

## Troubleshooting

* **"ERROR: Vosk model path not found"**: Ensure `VOSK_MODEL_PATH` in the script correctly points to your downloaded and extracted Vosk model folder.
* **"ERROR: Vosk library not installed."**: Run `pip install vosk`.
* **SDR not found / rtlsdr errors**:
    * Ensure your RTL-SDR dongle is properly connected.
    * Verify that the necessary drivers (e.g., Zadig on Windows for librtlsdr) are installed and working.
    * On Linux, you might need to blacklist default kernel drivers (e.g., `dvb_usb_rtl28xxu`) by creating a file in `/etc/modprobe.d/`.
* **No TTS output / TTS errors**:
    * **Linux**: Ensure `spd-say` (from `speech-dispatcher`) or `espeak` is installed. The script tries `spd-say` first.
    * **Windows/macOS**: TTS should generally work out-of-the-box. Check system audio settings if no sound is produced.
    * Review console logs for specific error messages from the TTS subprocess.
* **No Transmission / Radio Not Keying**:
    * Verify the APRS-K1 Pro cable (or similar) is securely connected to both the computer's audio output and the radio.
    * Ensure the correct audio output device is selected in your computer's sound settings and that the volume is up.
    * Check the radio's PTT mechanism; if it relies on VOX and your cable is only audio, ensure VOX is enabled and sensitive enough on the radio. The APRS-K1 Pro is generally designed to handle PTT directly.
    * Confirm the radio is powered on and on the correct transmit frequency.
    * Test the cable and radio PTT function independently if possible (e.g., by playing a sound from the computer and seeing if it keys the radio).
* **Poor recognition accuracy**:
    * Ensure a quiet RF environment or adjust `RF_VAD_STD_MULTIPLIER`.
    * Try a larger, more accurate Vosk model (though this will require more resources).
    * Ensure the `AUDIO_DOWNSAMPLE_RATE` matches what the Vosk model is trained for.
    * Speak clearly and relatively close to the microphone if testing with a local transmitter.
* **"VAD: Triggered! Starting capture." but no STT result**:
    * The audio might be too short (less than `VAD_MIN_SPEECH_SAMPLES`).
    * The audio quality might be too poor for Vosk to recognize anything.
    * The speech might not contain words from the defined `VOSK_VOCABULARY`/`VOSK_GRAMMAR_STR`.

## License

This project is open-source. Please feel free to modify and distribute. If no specific license is chosen, consider it under MIT or Apache 2.0, or specify your own. (Currently, no license file is provided with the script).
