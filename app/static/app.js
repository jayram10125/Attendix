document.querySelectorAll('[data-camera]').forEach(panel => {
  const video = panel.querySelector('video');
  const canvas = panel.querySelector('canvas');
  const status = panel.querySelector('.camera-status');
  const start = panel.querySelector('.start-camera');
  const capture = panel.querySelector('.capture-camera');
  const multi = panel.dataset.multi === 'true';
  const photos = [];
  let stream;
  start.addEventListener('click', async () => {
    try {
      if (!navigator.mediaDevices?.getUserMedia) throw new Error('Camera needs HTTPS or localhost.');
      photos.length = 0;
      panel.querySelector('input[type=hidden]').value = '';
      stream?.getTracks().forEach(track => track.stop());
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 640 } }, audio: false });
      video.srcObject = stream;
      capture.disabled = false;
      status.textContent = multi ? 'Photo 1 of 3: look straight ahead.' : 'Camera ready. Look straight ahead and capture.';
    } catch (error) { status.textContent = error.message || 'Camera access failed.'; }
  });
  capture.addEventListener('click', () => {
    if (!video.videoWidth) return;
    const scale = Math.min(1, 640 / video.videoWidth);
    canvas.width = Math.round(video.videoWidth * scale);
    canvas.height = Math.round(video.videoHeight * scale);
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    const photo = canvas.toDataURL('image/jpeg', .82);
    if (multi) {
      photos.push(photo);
      status.textContent = photos.length === 3 ? 'All 3 photos captured. Save your face reference.' : `Photo ${photos.length} of 3 captured. ${photos.length === 1 ? 'Turn slightly left' : 'Turn slightly right'} for the next photo.`;
      if (photos.length === 3) {
        panel.querySelector('[name=photos]').value = JSON.stringify(photos);
        stream?.getTracks().forEach(track => track.stop());
        video.srcObject = null;
        capture.disabled = true;
      }
    } else {
      panel.querySelector('[name=photo]').value = photo;
      status.textContent = 'Photo captured. You can submit now.';
      stream?.getTracks().forEach(track => track.stop());
      video.srcObject = null;
      capture.disabled = true;
    }
  });
  window.addEventListener('pagehide', () => stream?.getTracks().forEach(track => track.stop()));
});

document.querySelectorAll('[data-get-location]').forEach(button => {
  button.addEventListener('click', () => {
    const form = button.closest('form');
    const status = form.querySelector('[data-location-status]');
    if (!navigator.geolocation) { status.textContent = 'Location is unavailable in this browser.'; return; }
    status.textContent = 'Getting your location…';
    navigator.geolocation.getCurrentPosition(position => {
      form.querySelector('[name=latitude]').value = position.coords.latitude;
      form.querySelector('[name=longitude]').value = position.coords.longitude;
      status.textContent = `Location captured (accuracy approximately ${Math.round(position.coords.accuracy)} m).`;
    }, error => { status.textContent = error.message || 'Allow location access and try again.'; }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
  });
});

document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
  if (form.id === 'student-form' && !form.querySelector('[name=photos]')?.value) {
    event.preventDefault(); alert('Capture all 3 student face photos before registration.');
  }
}));

const kioskForm = document.querySelector('#kiosk-form');
if (kioskForm) {
  const button = document.querySelector('#start-attendance');
  const video = kioskForm.querySelector('video');
  const canvas = kioskForm.querySelector('canvas');
  const status = document.querySelector('#kiosk-status');
  let stream;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try {
      if (!navigator.mediaDevices?.getUserMedia || !navigator.geolocation) throw new Error('Camera and location need localhost or HTTPS.');
      status.textContent = 'Opening camera…';
      stream = await navigator.mediaDevices.getUserMedia({video:{facingMode:'user',width:{ideal:640}},audio:false});
      video.srcObject = stream;
      video.hidden = false;
      await video.play();
      status.textContent = 'Look straight into the camera. Checking your location…';
      const locationPromise = new Promise((resolve, reject) => navigator.geolocation.getCurrentPosition(resolve, reject, {enableHighAccuracy:true,timeout:15000,maximumAge:0}));
      await new Promise(resolve => setTimeout(resolve, 1800));
      const location = await locationPromise;
      const scale = Math.min(1, 640 / video.videoWidth);
      canvas.width = Math.round(video.videoWidth * scale);
      canvas.height = Math.round(video.videoHeight * scale);
      if (!canvas.width || !canvas.height) throw new Error('Camera image unavailable. Please retry.');
      canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
      kioskForm.querySelector('[name=photo]').value = canvas.toDataURL('image/jpeg', .82);
      kioskForm.querySelector('[name=latitude]').value = location.coords.latitude;
      kioskForm.querySelector('[name=longitude]').value = location.coords.longitude;
      status.textContent = 'Verifying face, location and schedule…';
      stream.getTracks().forEach(track => track.stop());
      video.hidden = true;
      kioskForm.submit();
    } catch (error) {
      status.textContent = error.message || 'Camera or location access failed. Please retry.';
      stream?.getTracks().forEach(track => track.stop());
      video.hidden = true;
      button.disabled = false;
    }
  });
  window.addEventListener('pagehide', () => stream?.getTracks().forEach(track => track.stop()));
}

