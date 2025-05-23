# OpenSignalReport

## Overview
OpenSignalReport is a modern, self-hosted signal reporting system for amateur radio, designed for Raspberry Pi or PC. It uses a Software Defined Radio (SDR) to listen for voice transmissions, automatically logs signal reports to a local SQLite database, and provides a user-friendly web interface for configuration, control, and log review. All processing is offline—no internet required.

---

## Features
- **Automated Signal Reports:** Listens for callsigns and the phrase "signal report" using an SDR and offline speech-to-text (Vosk).
- **Web Dashboard:** Local Flask web app for starting/stopping the SDR, editing config, and viewing logs with audio playback and spectrograms.
- **Modern UI:** Responsive, mobile-friendly interface with dark mode, loading indicators, and live status.
- **Robust Logging:** All reports, audio, and spectrograms are logged to SQLite and accessible via the web UI.
- **Configurable:** All SDR, VAD, and STT settings are editable via the web interface (`config.json`).
- **Process Management:** Start/stop/check SDR backend from the web UI, with live feedback and system resource display.
- **Audio Interface Support:** Designed for use with APRS-K1 PRO or similar audio/PTT cables for analog radio transmission.

---

## Quick Start
1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
2. **Download a Vosk model:**
   - [Vosk Models Page](https://alphacephei.com/vosk/models)
   - Extract and set the path in `config.json`.
3. **Configure:**
   - Edit `config.json` or use the web UI `/config` page.
4. **Run the web app:**
   ```bash
   python webapp.py
   ```
   - Open `http://localhost:5000` in your browser.
5. **Connect hardware:**
   - SDR dongle, antenna, and (optional) APRS-K1 PRO cable to your analog radio.
6. **Start SDR:**
   - Use the web UI **Run** page to start/stop the SDR and view live status.

---

## Web Interface
- **Run:** Start/stop SDR, view live status, uptime, system resources, and logs.
- **Config:** Edit all SDR/VAD/STT settings with validation and feedback.
- **Logs:** Browse, search, and play back signal reports. View audio and spectrograms in-browser.
- **Dark Mode:** Toggle in the top right corner. Theme is persistent.

---

## Architecture
- **Backend:** Python 3, Flask, SQLite, Vosk STT, psutil, matplotlib.
- **Frontend:** Jinja2 templates, static CSS/JS, responsive design.
- **Logging:** All signal reports, audio, and spectrograms are stored locally. No cloud or external dependencies.
- **Process Management:** Robust detection and control of SDR backend (`sigrep.py`).

---

## File Structure
- `sigrep.py` — SDR/STT backend, logs to SQLite, writes status for web UI
- `signal_db.py` — SQLite logic
- `webapp.py` — Flask web frontend
- `config.json` — All SDR/VAD/web config
- `signal_reports.db` — SQLite database
- `wavs/` — Captured audio and spectrograms
- `templates/` — Jinja2 HTML templates
- `static/` — CSS/JS assets

---

## Hardware & Prerequisites
- **Python 3.7+**
- **RTL-SDR dongle** (e.g., RTL-SDR Blog V4)
- **Antenna** for target frequency
- **Vosk model** (see above)
- **(Optional) APRS-K1 PRO cable** for analog radio transmission

---

## Configuration
All settings are in `config.json` and editable via the web UI:
- **SDR:** Frequency (MHz), sample rate, gain, offset
- **VAD:** Noise baseline, trigger threshold, capture duration
- **STT:** Vosk model path, vocabulary
- **Logging:** Audio/spectrogram saving

---

## Usage Notes
- **Audio/PTT:** Adjust PC output and radio mic gain for clean transmission. See web UI and docs for tips.
- **Logs:** All reports, audio, and spectrograms are viewable and downloadable from the web UI.
- **Shutdown:** Stop the SDR from the web UI before disconnecting hardware.

---

## Advanced
- **Migration:** Use `migrate_csv_to_sqlite.py` to import old CSV logs.
- **Manual Control:** You can run `sigrep.py` directly for CLI-only operation.
- **Customization:** Extend templates/static files for custom UI/UX.

---

## Disclaimer
This software is for experimental and educational use. Operate in accordance with your amateur radio license and local regulations. You are responsible for all transmissions.

---

## Credits
- SDR: [pyrtlsdr](https://github.com/roger-/pyrtlsdr)
- STT: [Vosk](https://alphacephei.com/vosk/)
- UI: Flask, Jinja2, Bootstrap-inspired CSS

---

## License
MIT License. See `LICENSE` file.
