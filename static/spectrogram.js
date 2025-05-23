let scale = 1.0;
let originX = 0, originY = 0;
let isPanning = false, startX = 0, startY = 0, imgX = 0, imgY = 0;
const img = document.getElementById('spectrogram-img');
const container = document.getElementById('spectrogram-container');
function updateTransform() {
  img.style.transform = `scale(${scale}) translate(${imgX/scale}px,${imgY/scale}px)`;
}
function zoomIn() {
  scale = Math.min(scale * 1.25, 10);
  updateTransform();
}
function zoomOut() {
  scale = Math.max(scale / 1.25, 0.2);
  updateTransform();
}
function resetZoom() {
  scale = 1.0; imgX = 0; imgY = 0;
  updateTransform();
}
img.addEventListener('mousedown', function(e) {
  isPanning = true;
  startX = e.clientX - imgX;
  startY = e.clientY - imgY;
  img.style.cursor = 'grabbing';
});
document.addEventListener('mousemove', function(e) {
  if (!isPanning) return;
  imgX = e.clientX - startX;
  imgY = e.clientY - startY;
  updateTransform();
});
document.addEventListener('mouseup', function(e) {
  isPanning = false;
  img.style.cursor = 'grab';
});
img.addEventListener('wheel', function(e) {
  e.preventDefault();
  if (e.deltaY < 0) zoomIn();
  else zoomOut();
});
// Touch support for mobile
let lastTouchDist = null;
img.addEventListener('touchstart', function(e) {
  if (e.touches.length === 2) {
    lastTouchDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
  } else if (e.touches.length === 1) {
    isPanning = true;
    startX = e.touches[0].clientX - imgX;
    startY = e.touches[0].clientY - imgY;
  }
});
img.addEventListener('touchmove', function(e) {
  if (e.touches.length === 2 && lastTouchDist !== null) {
    let newDist = Math.hypot(
      e.touches[0].clientX - e.touches[1].clientX,
      e.touches[0].clientY - e.touches[1].clientY
    );
    let factor = newDist / lastTouchDist;
    scale = Math.max(0.2, Math.min(10, scale * factor));
    lastTouchDist = newDist;
    updateTransform();
  } else if (e.touches.length === 1 && isPanning) {
    imgX = e.touches[0].clientX - startX;
    imgY = e.touches[0].clientY - startY;
    updateTransform();
  }
});
img.addEventListener('touchend', function(e) {
  if (e.touches.length < 2) lastTouchDist = null;
  if (e.touches.length === 0) isPanning = false;
});
