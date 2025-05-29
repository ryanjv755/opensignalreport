# OpenSignalReport

**OpenSignalReport** is an easy-to-use, web-based tool for monitoring, logging, and analyzing radio signals using affordable SDR (Software Defined Radio) hardware. Designed with ham radio operators in mind, it helps you track signal reports, test coverage, and even play back your own transmissions—all from your web browser!

---

## Why Use OpenSignalReport?

- **See Your Signal**: Instantly view S-meter and SNR readings for your transmissions, with logs and audio recordings you can play back anytime.
- **Visualize Your Audio**: Every transmission gets a spectrogram—see your CTCSS tones, DTMF digits, and voice patterns at a glance.
- **Speech-to-Text**: Your callsign and signal report are automatically transcribed, making it easy to search and review logs.
- **Parrot Mode**: Want to hear how you sound on the air? Enable parrot mode and the system will play your transmission back to you!
- **Works with Your Gear**: Connects to your radio using a simple audio cable or an APRS interface cable (like the [APRS-K1 PRO](https://baofengtech.com/product/aprs-k1-pro/?srsltid=AfmBOopnNXi16b9c9FxdsNchWfNEKcn19wrvadcB7dly1ryjx8187Wy-)).
- **No Cloud Required**: All processing is done locally—your audio and logs stay private.
- **Fully Configurable**: Adjust SDR, audio, and web settings from a friendly web interface.

---

## Features

- **SDR Audio Monitoring**: Uses RTL-SDR to capture and process FM audio.
- **CTCSS Detection**: Detects CTCSS tones to trigger audio capture.
- **DTMF Detection**: Supports DTMF digit detection and parrot mode.
- **Speech-to-Text**: Integrates with Vosk for offline STT transcription.
- **Text-to-Speech (TTS) Retransmission**: Can retransmit messages or reports using TTS audio output via a VOX cable or APRS interface cable (such as the [APRS-K1 PRO](https://baofengtech.com/product/aprs-k1-pro/?srsltid=AfmBOopnNXi16b9c9FxdsNchWfNEKcn19wrvadcB7dly1ryjx8187Wy-)).
- **Signal Metrics**: Logs S-meter, SNR, and duration for each transmission.
- **Web Dashboard**: View logs, play audio, and see spectrograms in your browser.
- **Configurable**: All major parameters are editable via the web UI.
- **Baselining**: Automatic noise and CTCSS threshold calibration at startup.

---

## What Can You Do With It?

- **Test your coverage**: Walk or drive around and see how your signal changes—great for repeater owners or anyone curious about their range.
- **Compare antennas and radios**: Log and compare performance with different setups.
- **Troubleshoot audio**: Use spectrograms and recordings to spot distortion, interference, or missed tones.
- **Automate logging**: Keep a searchable, timestamped record of all your on-air activity.

---

## Quick Start

1. **Install Requirements**
   - Python 3.8+
   - [RTL-SDR drivers](https://osmocom.org/projects/rtl-sdr/wiki/Rtl-sdr)
   - [librtlsdr.dll](https://github.com/librtlsdr/librtlsdr/releases) and [libusb-1.0.dll](https://libusb.info/)  
     Place these DLLs in your Python, project, or system PATH on Windows.
   - `pip install -r requirements.txt`
   - **Vosk**:  
     - Install the Python package:  
       ```
       pip install vosk
       ```
     - Download a Vosk model (e.g., [vosk-model-small-en-us-0.15](https://alphacephei.com/vosk/models)) and extract it to a directory.  
       Set the path in your config.

2. **Configure**
   - Edit `config.json` or use the `/config` page in the web UI.

3. **Run the Server**
   ```sh
   python webapp.py
   ```
   - Visit `http://localhost:5000` (or your configured host/port).

4. **Start Signal Reporter**
   - Use the web UI "Run" page to start/stop the SDR signal processing.

---

## Hardware Setup: SDR to Radio (APRS/Audio Cable)

To use OpenSignalReport with a radio, you need to connect your radio’s audio output to your computer’s audio input (or directly to the SDR if using direct sampling). For best results, use a proper audio interface or APRS-style cable.


**If you use an RTL-SDR dongle, connect the antenna as usual. Audio is demodulated in software.**

---

## Spectrograms

For every captured transmission, OpenSignalReport generates a **spectrogram image** alongside the audio recording. The spectrogram provides a visual representation of the frequency content of the received signal over time, which can be useful for:

- Verifying the presence and quality of CTCSS tones.
- Diagnosing audio issues, interference, or unexpected signals.
- Visualizing speech and DTMF tones.

### How to View Spectrograms

- Go to the `/logs` page in your web browser.
- Each signal report entry includes a **thumbnail** of the spectrogram in the "Spectrogram" column.
- **Click the thumbnail** to view a larger version in an overlay modal.

Spectrogram images are saved in the `wavs/` directory alongside the corresponding audio files, and are accessible via the web interface.

---

## Usage

- **Logs**: View signal reports, play audio, and see spectrograms on the `/logs` page.
- **Config**: Edit SDR, audio, CTCSS, and web settings on the `/config` page.
- **Run**: Start/stop the SDR processing and see live status on the `/run` page.

---

## How to Perform a Signal Report

1. **Transmit with CTCSS**:  
   Key your radio and transmit with the configured CTCSS tone.  
   The system will detect the CTCSS, record the audio, and process the signal.

2. **Speak Clearly**:  
   For best results, use standard phonetic alphabet for your callsign and say "signal report" at the end.  
   Example:  
   ```
   "Kilo Romeo Four Delta Tango Tango signal report"
   ```

3. **Release PTT**:  
   After you finish speaking, release your PTT.  
   The system will process the audio, transcribe the speech, and log the report.

4. **View the Report**:  
   Go to the `/logs` page in your browser to see your signal report, play back the audio, and view the spectrogram.

---

## How to Use Parrot Mode

1. **Enable Parrot Mode via DTMF**:  
   While transmitting with CTCSS, send the DTMF sequence `#98` on your radio.  
   You should hear/see confirmation that "Parrot mode enabled".

2. **Transmit Your Message**:  
   After enabling, transmit your message as usual.  
   The system will record your audio.

3. **Playback**:  
   After you unkey, the system will automatically play back your recorded audio over the air.

4. **Disable Parrot Mode**:  
   To disable parrot mode, send the DTMF sequence `#99`.

---

## Directory Structure

```
opensignalreport/
├── sigrep.py           # Main SDR/audio processing engine
├── webapp.py           # Flask web server
├── signal_db.py        # SQLite logging functions
├── config.json         # Configuration file
├── wavs/               # Captured audio and spectrograms
├── static/             # Static files (JS, CSS)
│   └── run.js
├── templates/          # HTML templates
│   ├── base.html
│   ├── run.html
│   ├── logs.html
│   └── config.html
└── requirements.txt
```

---

## Ideas for Using Your Logs and Data

### 1. **Signal Strength Mapping**
- Export your logs (with S-meter/SNR and timestamps).
- Use a GPS logger or note your location at each test point.
- Plot S-meter/SNR vs. location on a map (e.g., with Google Maps, QGIS, or Python’s folium).
- Visualize coverage, dead spots, and the effect of obstacles.

### 2. **Antenna/Equipment Comparison**
- Repeat the same walk with different antennas or radios.
- Compare S-meter/SNR and STT accuracy for each setup.

### 3. **Propagation Studies**
- Test at different times of day or weather conditions.
- Analyze how SNR and signal quality change.

### 4. **Speech-to-Text Tuning**
- Review logs where callsign is “Unknown” or text is incorrect.
- Listen to the audio and adjust mic gain, STT model, or speaking style for better recognition.

### 5. **CTCSS/DTMF Reliability**
- Check how reliably CTCSS and DTMF are detected at different distances or with different radios.

### 6. **Spectrogram Analysis**
- Use the spectrograms to visually inspect audio quality, interference, or tone presence.
- Identify sources of noise or distortion.

### 7. **Automated Alerts or Reports**
- Set up scripts to email or notify you when a certain callsign or phrase is detected.
- Automatically generate daily/weekly signal reports.

### 8. **Integration with Other Systems**
- Feed logs into APRS, mapping, or repeater control systems.
- Use the data for club or public coverage reports.

---

## Notes

- Audio and spectrogram files are served from `/wavs/`.
- CTCSS threshold is auto-calibrated at startup unless set manually.
- All logs are stored in a local SQLite database.
- **On Windows:**  
  - Place `librtlsdr.dll` and `libusb-1.0.dll` in the same directory as your Python executable, your project root, or any directory in your system PATH.

---

## License

MIT License

---

**OpenSignalReport: See, hear, and log your signal—your way!**
