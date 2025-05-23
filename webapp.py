from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, flash
from signal_db import get_all_signal_reports, log_signal_report
import os
import glob
import json
import subprocess
import psutil
import time
import re

app = Flask(__name__)

CONFIG_PATH = 'config.json'
SIGREP_PROCESS_NAME = 'sigrep.py'
SIGREP_STATUS_FILE = 'sigrep_status.json'

def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)

# Helper to check if sigrep.py is running
def is_sigrep_running():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline'] and SIGREP_PROCESS_NAME in proc.info['cmdline']:
                return True
        except Exception:
            continue
    return False

# Helper to get status (loading/baselining/ready)
def get_sigrep_status():
    if not os.path.exists(SIGREP_STATUS_FILE):
        return {'state': 'stopped'}
    try:
        with open(SIGREP_STATUS_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {'state': 'unknown'}

# Start sigrep.py as a subprocess
def start_sigrep():
    if is_sigrep_running():
        return False
    subprocess.Popen(['python', SIGREP_PROCESS_NAME], creationflags=subprocess.CREATE_NEW_CONSOLE)
    return True

# Stop sigrep.py by killing the process
def stop_sigrep():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['cmdline'] and SIGREP_PROCESS_NAME in proc.info['cmdline']:
                proc.kill()
        except Exception:
            continue

@app.route('/')
def index():
    return redirect(url_for('run_status'))

# Add a navigation bar to all pages
NAVBAR = '''
<div style="background:#f5f5f5;padding:12px 0 12px 0;margin-bottom:24px;border-bottom:1px solid #ccc;">
  <a href="/run" style="margin:0 18px;font-weight:bold;text-decoration:none;color:#0078d7;">Run</a>
  <a href="/config" style="margin:0 18px;font-weight:bold;text-decoration:none;color:#0078d7;">Configuration</a>
  <a href="/logs" style="margin:0 18px;font-weight:bold;text-decoration:none;color:#0078d7;">Logs</a>
</div>
'''

# Global style for all pages
GLOBAL_STYLE = '''
<style>
  html, body { width: 100vw; overflow-x: hidden; }
  body { background: #f5f6fa; font-family: 'Segoe UI', 'Arial', sans-serif; margin: 0; min-height: 100vh; }
  .main-container { width: 100%; max-width: none; margin: 0; background: #fff; border-radius: 0; box-shadow: none; padding: 32px 28px 32px 28px; min-height: calc(100vh - 60px); box-sizing: border-box; }
  h1, h2, h3 { font-weight: 600; color: #222; }
  table { margin: 0 0 24px 0; border-collapse: collapse; background: #fafbfc; border-radius: 10px; box-shadow: 0 1px 8px #0001; width: 100%; }
  th, td { padding: 10px 14px; border-bottom: 1px solid #e0e0e0; text-align: left; }
  th { background: #f0f2f5; color: #0078d7; font-weight: 600; }
  tr:last-child td { border-bottom: none; }
  form { margin: 0; text-align: left; }
  fieldset { text-align: left; }
  label { display: block; margin-bottom: 8px; font-weight: 500; }
  input, select, textarea { font-family: inherit; border-radius: 5px; border: 1px solid #bbb; padding: 6px 8px; margin-bottom: 10px; width: 100%; box-sizing: border-box; }
  input[type="checkbox"] { width: auto; margin-left: 6px; }
  button, input[type=submit] { font-size: 1.1em; padding: 8px 24px; border-radius: 5px; background: #0078d7; color: #fff; border: none; cursor: pointer; transition: background 0.2s; }
  button:hover, input[type=submit]:hover { background: #005fa3; }
  audio { display: block; }
  .msg { font-size: 1.1em; margin-bottom: 18px; }
  @media (max-width: 700px) {
    .main-container { padding: 10px 2vw; }
    table, th, td { font-size: 0.98em; }
  }
</style>
'''

@app.route('/run', methods=['GET', 'POST'])
def run_status():
    message = ''
    if request.method == 'POST':
        if 'start' in request.form:
            if start_sigrep():
                message = 'Started sigrep.'
            else:
                message = 'sigrep is already running.'
        elif 'stop' in request.form:
            stop_sigrep()
            message = 'Stopped sigrep.'
        time.sleep(1)  # Give time for process to start/stop
    status = get_sigrep_status()
    running = is_sigrep_running()
    html = NAVBAR + GLOBAL_STYLE + '<div class="main-container">'
    html += '<h1>Run Status (Live)</h1>'
    if message:
        html += f'<div class="msg" style="color:blue;">{message}</div>'
    html += '<form method="post" style="margin-bottom:20px;">'
    if running:
        html += '<button name="stop" type="submit" style="background:#d9534f;">Stop Radio</button>'
    else:
        html += '<button name="start" type="submit" style="background:#5cb85c;">Start Radio</button>'
    html += '</form>'
    if running:
        if status.get('state') == 'baselining':
            html += '<div class="msg" style="color:orange;font-weight:bold;">Radio is baselining... Please wait.</div>'
        elif status.get('state') == 'ready':
            html += '<div class="msg" style="color:green;font-weight:bold;">Radio is running and ready.</div>'
        else:
            html += '<div class="msg" style="color:gray;">Radio is running (status unknown).</div>'
    else:
        html += '<div class="msg" style="color:red;">Radio is stopped.</div>'
    html += '</div>'
    return html

@app.route('/config', methods=['GET', 'POST'])
def config():
    cfg = load_config()
    error = None
    if request.method == 'POST':
        try:
            # Validate numeric fields
            center_freq = float(request.form['SDR_CENTER_FREQ'])
            if not (10.0 <= center_freq <= 6000.0):
                raise ValueError('Center frequency must be between 10 and 6000 MHz.')
            sample_rate = int(request.form['SDR_SAMPLE_RATE'])
            if not (8000 <= sample_rate <= 10_000_000):
                raise ValueError('Sample rate must be between 8,000 and 10,000,000 Hz.')
            gain = int(request.form['SDR_GAIN'])
            if not (0 <= gain <= 100):
                raise ValueError('Gain must be between 0 and 100 dB.')
            baseline = float(request.form['BASELINE_DURATION_SECONDS'])
            if not (0.1 <= baseline <= 600):
                raise ValueError('Baseline duration must be between 0.1 and 600 seconds.')
            vad_std = float(request.form['RF_VAD_STD_MULTIPLIER'])
            if not (0.01 <= vad_std <= 100):
                raise ValueError('VAD Std Multiplier must be between 0.01 and 100.')
            vad_capture = float(request.form['VAD_SPEECH_CAPTURE_SECONDS'])
            if not (0.1 <= vad_capture <= 60):
                raise ValueError('VAD Speech Capture must be between 0.1 and 60 seconds.')
            vad_min = float(request.form['VAD_MIN_SPEECH_SECONDS'])
            if not (0.01 <= vad_min <= 10):
                raise ValueError('VAD Min Speech must be between 0.01 and 10 seconds.')
            audio_down = int(request.form['AUDIO_DOWNSAMPLE_RATE'])
            if not (8000 <= audio_down <= 48000):
                raise ValueError('Audio Downsample Rate must be between 8000 and 48000 Hz.')
            nfm_cutoff = int(request.form['NFM_FILTER_CUTOFF'])
            if not (100 <= nfm_cutoff <= 20000):
                raise ValueError('NFM Filter Cutoff must be between 100 and 20000 Hz.')
            hpf_cutoff = int(request.form['HPF_CUTOFF_HZ'])
            if not (0 <= hpf_cutoff <= 1000):
                raise ValueError('HPF Cutoff must be between 0 and 1000 Hz.')
            hpf_order = int(request.form['HPF_ORDER'])
            if not (1 <= hpf_order <= 10):
                raise ValueError('HPF Order must be between 1 and 10.')
            web_port = int(request.form['WEB_PORT'])
            if not (1 <= web_port <= 65535):
                raise ValueError('Web port must be between 1 and 65535.')
            web_host = request.form['WEB_HOST']
            if not re.match(r'^[\w\.-]+$', web_host):
                raise ValueError('Web host contains invalid characters.')
            stt_engine = request.form['STT_ENGINE']
            if not stt_engine or len(stt_engine) > 64:
                raise ValueError('STT Engine must be non-empty and less than 64 characters.')
            vosk_path = request.form['VOSK_MODEL_PATH']
            if not vosk_path or len(vosk_path) > 256:
                raise ValueError('Vosk Model Path must be non-empty and less than 256 characters.')
            # Save validated values
            cfg['SDR_CENTER_FREQ'] = center_freq
            cfg['SDR_SAMPLE_RATE'] = sample_rate
            cfg['SDR_GAIN'] = gain
            cfg['SDR_OFFSET_TUNING'] = request.form.get('SDR_OFFSET_TUNING') == 'on'
            cfg['BASELINE_DURATION_SECONDS'] = baseline
            cfg['RF_VAD_STD_MULTIPLIER'] = vad_std
            cfg['VAD_SPEECH_CAPTURE_SECONDS'] = vad_capture
            cfg['VAD_MIN_SPEECH_SECONDS'] = vad_min
            cfg['AUDIO_DOWNSAMPLE_RATE'] = audio_down
            cfg['NFM_FILTER_CUTOFF'] = nfm_cutoff
            cfg['HPF_CUTOFF_HZ'] = hpf_cutoff
            cfg['HPF_ORDER'] = hpf_order
            cfg['SAVE_SPECTROGRAM'] = request.form.get('SAVE_SPECTROGRAM') == 'on'
            cfg['STT_ENGINE'] = stt_engine
            cfg['VOSK_MODEL_PATH'] = vosk_path
            cfg['WEB_PORT'] = web_port
            cfg['WEB_HOST'] = web_host
            save_config(cfg)
            return redirect(url_for('config'))
        except Exception as e:
            error = str(e)
    checked_offset = 'checked' if cfg.get('SDR_OFFSET_TUNING') else ''
    checked_spec = 'checked' if cfg.get('SAVE_SPECTROGRAM') else ''
    center_freq_val = cfg['SDR_CENTER_FREQ']
    if center_freq_val >= 1e6 and center_freq_val % 1e6 == 0:
        center_freq_display = str(center_freq_val / 1e6)
    elif center_freq_val >= 1e6 and center_freq_val < 2e9:
        center_freq_display = f"{center_freq_val / 1e6:.3f}"
    else:
        center_freq_display = str(center_freq_val)
    html = NAVBAR + GLOBAL_STYLE + f'''
    <div class="main-container">
    <h1>Configuration</h1>
    {'<div class="msg" style="color:red;">'+error+'</div>' if error else ''}
    <form method="post" style="max-width:500px;margin:20px 0 20px 0;padding:20px;border:1px solid #ccc;border-radius:8px;background:#f9f9f9;">
      <fieldset style="margin-bottom:18px;padding:10px 15px;border-radius:6px;border:1px solid #bbb;">
        <legend style="font-weight:bold;">SDR Settings</legend>
        <label>Center Frequency (MHz):<br><input name="SDR_CENTER_FREQ" type="number" value="{center_freq_display}" step="0.001" style="width:100%"></label><br>
        <label>Sample Rate (Hz):<br><input name="SDR_SAMPLE_RATE" type="number" value="{cfg['SDR_SAMPLE_RATE']}" step="1" style="width:100%"></label><br>
        <label>Gain (dB):<br><input name="SDR_GAIN" type="number" value="{cfg['SDR_GAIN']}" step="1" style="width:100%"></label><br>
        <label>Offset Tuning: <input name="SDR_OFFSET_TUNING" type="checkbox" {checked_offset}></label>
      </fieldset>
      <fieldset style="margin-bottom:18px;padding:10px 15px;border-radius:6px;border:1px solid #bbb;">
        <legend style="font-weight:bold;">VAD & Audio Processing</legend>
        <label>Baseline Duration (s):<br><input name="BASELINE_DURATION_SECONDS" type="number" value="{cfg['BASELINE_DURATION_SECONDS']}" step="0.1" style="width:100%"></label><br>
        <label>RF VAD Std Multiplier:<br><input name="RF_VAD_STD_MULTIPLIER" type="number" value="{cfg['RF_VAD_STD_MULTIPLIER']}" step="0.01" style="width:100%"></label><br>
        <label>VAD Speech Capture (s):<br><input name="VAD_SPEECH_CAPTURE_SECONDS" type="number" value="{cfg['VAD_SPEECH_CAPTURE_SECONDS']}" step="0.1" style="width:100%"></label><br>
        <label>VAD Min Speech (s):<br><input name="VAD_MIN_SPEECH_SECONDS" type="number" value="{cfg['VAD_MIN_SPEECH_SECONDS']}" step="0.01" style="width:100%"></label><br>
        <label>Audio Downsample Rate (Hz):<br><input name="AUDIO_DOWNSAMPLE_RATE" type="number" value="{cfg['AUDIO_DOWNSAMPLE_RATE']}" step="1" style="width:100%"></label><br>
        <label>NFM Filter Cutoff (Hz):<br><input name="NFM_FILTER_CUTOFF" type="number" value="{cfg['NFM_FILTER_CUTOFF']}" step="1" style="width:100%"></label><br>
        <label>HPF Cutoff (Hz):<br><input name="HPF_CUTOFF_HZ" type="number" value="{cfg['HPF_CUTOFF_HZ']}" step="1" style="width:100%"></label><br>
        <label>HPF Order:<br><input name="HPF_ORDER" type="number" value="{cfg['HPF_ORDER']}" step="1" style="width:100%"></label><br>
      </fieldset>
      <fieldset style="margin-bottom:18px;padding:10px 15px;border-radius:6px;border:1px solid #bbb;">
        <legend style="font-weight:bold;">Spectrogram & Web UI</legend>
        <label>Save Spectrogram: <input name="SAVE_SPECTROGRAM" type="checkbox" {checked_spec}></label><br>
        <label>STT Engine:<br><input name="STT_ENGINE" type="text" value="{cfg['STT_ENGINE']}" style="width:100%"></label><br>
        <label>Vosk Model Path:<br><input name="VOSK_MODEL_PATH" type="text" value="{cfg['VOSK_MODEL_PATH']}" style="width:100%"></label><br>
        <label>Web Host:<br><input name="WEB_HOST" type="text" value="{cfg['WEB_HOST']}" style="width:100%"></label><br>
        <label>Web Port:<br><input name="WEB_PORT" type="number" value="{cfg['WEB_PORT']}" step="1" style="width:100%"></label><br>
      </fieldset>
      <div style="margin-top:20px;">
        <input type="submit" value="Save">
      </div>
    </form>
    </div>
    '''
    return html

@app.route('/logs')
def logs():
    reports = get_all_signal_reports()
    html = NAVBAR + GLOBAL_STYLE + '''<div class="main-container"><h1>Signal Reports Log</h1><table border=0>
    <tr><th>Timestamp</th><th>Callsign</th><th>S-Meter</th><th>SNR</th><th>Duration</th><th>Text</th><th>Play</th><th style="width:120px;">Spectrogram</th></tr>'''
    for r in reports:
        uid = r[0]
        # Find WAV file
        wav_files = glob.glob(f'wavs/vad_capture_*_{uid}*.wav')
        wav_player = ''
        if wav_files:
            wav_url = f'/wavs/{os.path.basename(wav_files[0])}'
            wav_player = f'<audio controls style="width:120px;"><source src="{wav_url}" type="audio/wav">Your browser does not support the audio element.</audio>'
        # Find PNG spectrogram file (should match vad_capture_*_{uid}*.png)
        png_files = glob.glob(f'wavs/vad_capture_*_{uid}*.png')
        png_link = ''
        if png_files:
            png_url = f'/spectrogram/{os.path.basename(png_files[0])}'
            png_link = f'<a href="{png_url}" target="_blank"><img src="/wavs/{os.path.basename(png_files[0])}" alt="Spectrogram" style="max-width:220px;max-height:120px;display:block;margin:0 auto;"></a>'
        # Format SNR to 2 decimals
        try:
            snr_val = float(r[4])
            snr_display = f"{snr_val:.2f}"
        except Exception:
            snr_display = r[4]
        html += f'<tr><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{snr_display}</td><td>{r[5]}</td><td>{r[7]}</td><td>{wav_player}</td><td>{png_link}</td></tr>'
    html += '</table></div>'
    return html

@app.route('/spectrogram/<filename>')
def spectrogram_page(filename):
    # Show the spectrogram image on its own page
    img_url = f'/wavs/{filename}'
    html = NAVBAR + GLOBAL_STYLE + f'<div class="main-container"><h1>Spectrogram</h1><div><img src="{img_url}" style="max-width:180vw;max-height:160vh;"></div></div>'
    return html

@app.route('/wavs/<path:filename>')
def serve_wavs(filename):
    return send_from_directory(os.path.join(os.getcwd(), 'wavs'), filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
