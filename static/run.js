document.addEventListener('DOMContentLoaded', function() {
  function fetchStatus() {
    fetch('/run_status_json').then(r=>r.json()).then(data=>{
      let s = data;
      let html = '';
      if (s.running) {
        if (s.state === 'initializing') html += '<div class="msg" style="color:blue;font-weight:bold;">SigRep is initializing...</div>';
        else if (s.state === 'baselining') html += '<div class="msg" style="color:orange;font-weight:bold;">SigRep is baselining... Please wait.</div>';
        else if (s.state === 'ready') html += '<div class="msg" style="color:green;font-weight:bold;">SigRep is running and ready.</div>';
        else html += '<div class="msg" style="color:gray;">SigRep is running (status unknown).</div>';
      } else {
        html += '<div class="msg" style="color:red;">SigRep is stopped.</div>';
      }
      if (s.error) html += '<div class="msg" style="color:red;">'+s.error+'</div>';
      document.getElementById('status-block').innerHTML = html;
      // Button state
      document.getElementById('start-btn').disabled = s.running;
      document.getElementById('stop-btn').disabled = !s.running;
    });
  }
  setInterval(fetchStatus, 3000);
  fetchStatus();
  // Toast feedback
  function showToast(msg, color) {
    let t = document.getElementById('toast');
    t.innerText = msg;
    t.style.background = color || '#222';
    t.style.display = 'block';
    setTimeout(()=>{t.style.display='none';}, 3000);
  }
  let msg = window.run_message;
  let err = window.run_error;
  if (msg && msg.length > 0) showToast(msg, '#0078d7');
  if (err && err.length > 0) showToast(err, '#d9534f');
});
