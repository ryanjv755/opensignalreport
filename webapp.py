from flask import Flask, render_template, request, redirect, url_for, jsonify, send_from_directory, flash
from signal_db import get_all_signal_reports, log_signal_report
import os
import glob
import json
import subprocess
import psutil
import time
import re
import sys

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
    abs_script = os.path.abspath(SIGREP_PROCESS_NAME)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if not cmdline:
                continue
            # Check for both script name and absolute path
            if any((SIGREP_PROCESS_NAME in arg or abs_script in arg) for arg in cmdline):
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
    try:
        log_path = os.path.join(os.getcwd(), 'sigrep_webapp_launch.log')
        with open(log_path, 'a') as logf:
            logf.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] Attempting to start sigrep.py\n")
            proc = subprocess.Popen([
                sys.executable, os.path.abspath(SIGREP_PROCESS_NAME)
            ], cwd=os.path.dirname(os.path.abspath(SIGREP_PROCESS_NAME)), stdout=logf, stderr=logf)
            logf.write(f"Started sigrep.py with PID {proc.pid}\n")
        return True
    except Exception as e:
        with open('sigrep_webapp_launch.log', 'a') as logf:
            logf.write(f"Failed to start sigrep.py: {e}\n")
        return False

# Stop sigrep.py by killing the process
def stop_sigrep():
    abs_script = os.path.abspath(SIGREP_PROCESS_NAME)
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            cmdline = proc.info['cmdline']
            if not cmdline:
                continue
            # Match both script name and absolute path
            if any((SIGREP_PROCESS_NAME in arg or abs_script in arg) for arg in cmdline):
                proc.kill()
        except Exception:
            continue

@app.route('/')
def index():
    return redirect(url_for('run_status'))

# Add a navigation bar to all pages
NAVBAR = '''
<div class="navbar">
  <div class="nav-links">
    <a href="/run">Run</a>
    <a href="/config">Configuration</a>
    <a href="/logs">Logs</a>
  </div>
  <button id="theme-toggle" class="theme-toggle" onclick="toggleTheme()">Toggle Dark Mode</button>
</div>
'''

# Global style for all pages
GLOBAL_STYLE = '''
<style id="theme-style">
  html, body { width: 100vw; overflow-x: hidden; }
  body { background: var(--bg, #f5f6fa); font-family: 'Segoe UI', 'Arial', sans-serif; margin: 0; min-height: 100vh; color: var(--fg, #222); }
  .main-container { width: 100%; max-width: none; margin: 0; background: var(--card, #fff); border-radius: 0; box-shadow: none; padding: 32px 28px 32px 28px; min-height: calc(100vh - 60px); box-sizing: border-box; }
  h1, h2, h3 { font-weight: 600; color: var(--fg, #222); }
  table { margin: 0 0 24px 0; border-collapse: collapse; background: var(--table, #fafbfc); border-radius: 10px; box-shadow: 0 1px 8px #0001; width: 100%; }
  th, td { padding: 10px 14px; border-bottom: 1px solid var(--border, #e0e0e0); text-align: left; }
  th { background: var(--th, #f0f2f5); color: #0078d7; font-weight: 600; }
  tr:last-child td { border-bottom: none; }
  form { margin: 0; text-align: left; }
  fieldset { text-align: left; border: 1px solid var(--border, #bbb); background: var(--card, #fff); }
  legend { color: var(--fg, #222); font-weight: bold; }
  label { display: block; margin-bottom: 8px; font-weight: 500; color: var(--fg, #222); }
  input, select, textarea { font-family: inherit; border-radius: 5px; border: 1px solid var(--border, #bbb); padding: 6px 8px; margin-bottom: 10px; width: 100%; box-sizing: border-box; background: var(--inputbg, #fff); color: var(--fg, #222); }
  input[type="checkbox"] { width: auto; margin-left: 6px; }
  button, input[type=submit] { font-size: 1.1em; padding: 8px 24px; border-radius: 5px; background: #0078d7; color: #fff; border: none; cursor: pointer; transition: background 0.2s; }
  button:hover, input[type=submit]:hover { background: #005fa3; }
  audio { display: block; }
  .msg { font-size: 1.1em; margin-bottom: 18px; }
  .spinner { display: none; margin: 0 auto 18px auto; border: 6px solid #f3f3f3; border-top: 6px solid #0078d7; border-radius: 50%; width: 40px; height: 40px; animation: spin 1s linear infinite; }
  @keyframes spin { 100% { transform: rotate(360deg); } }
  .theme-toggle { position: fixed; top: 12px; right: 24px; z-index: 1000; background: #eee; color: #222; border: 1px solid #bbb; border-radius: 18px; padding: 6px 18px; font-size: 1em; cursor: pointer; }
  .theme-toggle.dark { background: #222; color: #eee; border: 1px solid #444; }
  .navbar { background: var(--navbg, #f5f5f5); border-bottom: 1px solid var(--border, #ccc); }
  .navbar a { color: #0078d7; }
  .navbar a:visited { color: #0078d7; }
  .navbar.dark { background: #181a1b; border-bottom: 1px solid #444; }
  .navbar.dark a { color: #4ea1ff; }
  @media (max-width: 700px) {
    .main-container { padding: 10px 2vw; }
    table, th, td { font-size: 0.98em; }
    .theme-toggle { top: 8px; right: 8px; font-size: 0.95em; }
  }
</style>
<script>
function setTheme(dark) {
  if (dark) {
    document.documentElement.style.setProperty('--bg', '#181a1b');
    document.documentElement.style.setProperty('--fg', '#eee');
    document.documentElement.style.setProperty('--card', '#23272b');
    document.documentElement.style.setProperty('--table', '#23272b');
    document.documentElement.style.setProperty('--th', '#222');
    document.documentElement.style.setProperty('--border', '#444');
    document.documentElement.style.setProperty('--inputbg', '#181a1b');
    document.documentElement.style.setProperty('--navbg', '#181a1b');
    var nav = document.getElementById('navbar');
    if (nav) nav.classList.add('dark');
    document.getElementById('theme-toggle').classList.add('dark');
    localStorage.setItem('theme', 'dark');
  } else {
    document.documentElement.style.setProperty('--bg', '#f5f6fa');
    document.documentElement.style.setProperty('--fg', '#222');
    document.documentElement.style.setProperty('--card', '#fff');
    document.documentElement.style.setProperty('--table', '#fafbfc');
    document.documentElement.style.setProperty('--th', '#f0f2f5');
    document.documentElement.style.setProperty('--border', '#e0e0e0');
    document.documentElement.style.setProperty('--inputbg', '#fff');
    document.documentElement.style.setProperty('--navbg', '#f5f5f5');
    var nav = document.getElementById('navbar');
    if (nav) nav.classList.remove('dark');
    document.getElementById('theme-toggle').classList.remove('dark');
    localStorage.setItem('theme', 'light');
  }
}
function toggleTheme() {
  var dark = localStorage.getItem('theme') === 'dark';
  setTheme(!dark);
}
document.addEventListener('DOMContentLoaded', function() {
  var dark = localStorage.getItem('theme') === 'dark';
  setTheme(dark);
});
</script>
'''

@app.route('/run', methods=['GET', 'POST'])
def run_status():
    cfg = load_config()
    message = ''
    error = ''
    if request.method == 'POST':
        try:
            action = None
            if 'start' in request.form:
                action = 'start'
            elif 'stop' in request.form:
                action = 'stop'
            elif 'restart' in request.form:
                action = 'restart'
            with open('sigrep_webapp_launch.log', 'a') as logf:
                logf.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] /run POST action: {action}\n")
            print(f"/run POST action: {action}")
            if action == 'start':
                result = start_sigrep()
                if result:
                    message = 'Started SignalReport.'
                else:
                    error = 'Failed to start SignalReport. See sigrep_webapp_launch.log.'
            elif action == 'stop':
                stop_sigrep()
                message = 'Stopped SignalReport.'
            elif action == 'restart':
                stop_sigrep()
                time.sleep(1)
                result = start_sigrep()
                if result:
                    message = 'Restarted SignalReport.'
                else:
                    error = 'Failed to restart SignalReport. See sigrep_webapp_launch.log.'
        except Exception as e:
            error = str(e)
            with open('sigrep_webapp_launch.log', 'a') as logf:
                logf.write(f"Exception in /run POST: {e}\n")
        time.sleep(1)
    status = get_sigrep_status()
    running = is_sigrep_running()
    last_started = status.get('last_started', None)
    if last_started and last_started != 'N/A':
        try:
            t = time.strptime(last_started, '%Y-%m-%d %H:%M:%S')
            last_started_fmt = time.strftime('%b %d, %Y %H:%M:%S', t)
            uptime_sec = int(time.time() - time.mktime(t))
            uptime_str = f"{uptime_sec//3600}h {(uptime_sec%3600)//60}m {uptime_sec%60}s"
        except Exception:
            last_started_fmt = last_started
            uptime_str = 'Unknown'
    else:
        last_started_fmt = 'N/A'
        uptime_str = 'N/A'
    cpu = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage('.')
    freq_mhz = float(cfg['SDR_CENTER_FREQ'])/1e6
    sample_rate = cfg['SDR_SAMPLE_RATE']
    gain = cfg['SDR_GAIN']
    return render_template(
        'run.html',
        navbar=NAVBAR,
        title='Run',
        cpu=f"{cpu:.1f}",
        ram=f"{mem.percent:.1f}",
        disk=f"{disk.percent:.1f}",
        freq_mhz=f"{freq_mhz:.3f}",
        sample_rate=sample_rate,
        gain=gain,
        uptime_str=uptime_str,
        last_started_fmt=last_started_fmt,
        message=message,
        error=error,
        running=running,
        status=status
    )

@app.route('/run_status_json')
def run_status_json():
    status = get_sigrep_status()
    running = is_sigrep_running()
    resp = {
        'running': running,
        'state': status.get('state', 'unknown'),
        'error': status.get('error', None)
    }
    return jsonify(resp)

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
            gain = float(request.form['SDR_GAIN'])
            if not (0 <= gain <= 100):
                raise ValueError('Gain must be between 0 and 100 dB.')
            baseline = float(request.form['BASELINE_DURATION_SECONDS'])
            if not (0.1 <= baseline <= 600):
                raise ValueError('Baseline duration must be between 0.1 and 600 seconds.')
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
            ctcss_freq = float(request.form['CTCSS_FREQ'])
            ctcss_threshold = request.form['CTCSS_THRESHOLD']
            ctcss_holdtime = float(request.form['CTCSS_HOLDTIME'])
            min_trans_len = float(request.form['MIN_TRANSMISSION_LENGTH'])
            save_spec = request.form.get('SAVE_SPECTROGRAM') == 'on'
            stt_engine = request.form['STT_ENGINE']
            vosk_path = request.form['VOSK_MODEL_PATH']
            web_port = int(request.form['WEB_PORT'])
            web_host = request.form['WEB_HOST']
            # Save validated values
            cfg['SDR_CENTER_FREQ'] = center_freq
            cfg['SDR_SAMPLE_RATE'] = sample_rate
            cfg['SDR_GAIN'] = gain
            cfg['SDR_OFFSET_TUNING'] = request.form.get('SDR_OFFSET_TUNING') == 'on'
            cfg['BASELINE_DURATION_SECONDS'] = baseline
            cfg['AUDIO_DOWNSAMPLE_RATE'] = audio_down
            cfg['NFM_FILTER_CUTOFF'] = nfm_cutoff
            cfg['HPF_CUTOFF_HZ'] = hpf_cutoff
            cfg['HPF_ORDER'] = hpf_order
            cfg['CTCSS_FREQ'] = ctcss_freq
            cfg['CTCSS_THRESHOLD'] = ctcss_threshold
            cfg['CTCSS_HOLDTIME'] = ctcss_holdtime
            cfg['MIN_TRANSMISSION_LENGTH'] = min_trans_len
            cfg['SAVE_SPECTROGRAM'] = save_spec
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
    return render_template(
        'config.html',
        navbar=NAVBAR,
        title='Configuration',
        cfg=cfg,
        checked_offset=checked_offset,
        checked_spec=checked_spec,
        center_freq_display=center_freq_display,
        error=error
    )

@app.route('/logs')
def logs():
    page = int(request.args.get('page', 1))
    per_page = 20  # or any number you prefer
    all_reports = get_all_signal_reports()
    total = len(all_reports)
    start = (page - 1) * per_page
    end = start + per_page
    reports = all_reports[start:end]
    total_pages = (total + per_page - 1) // per_page
    return render_template(
        'logs.html',
        reports=reports,
        page=page,
        total_pages=total_pages
    )

@app.route('/spectrogram/<filename>')
def spectrogram_page(filename):
    img_url = f'/wavs/{filename}'
    return render_template('spectrogram.html', navbar=NAVBAR, title='Spectrogram', img_url=img_url)

@app.route('/wavs/<path:filename>')
def serve_wavs(filename):
    return send_from_directory(os.path.join(os.getcwd(), 'wavs'), filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
