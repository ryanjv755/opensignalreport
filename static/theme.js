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
