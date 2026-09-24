/** Speech capture and command review. No browser/cloud speech-recognition service. */
export function initVoice({api, readSession, voice, applyResult}) {
  const $ = id => document.getElementById(id);
  let recorder = null, stream = null, timer = null, discard = false;
  let phase = 'idle', version = 0, previewText = null, request = null;
  const supported = Boolean(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
  const canRecord = voice.available && supported;
  $('voice-badge').textContent = voice.available ? 'Whisper · on device' : 'Typed commands ready';
  $('voice-status').textContent = voice.message + (!supported ? ' Microphone capture is unavailable in this browser; use a recording file.' : '');

  function controls() {
    $('record').disabled = !canRecord || !['idle', 'recording'].includes(phase);
    $('record').textContent = phase === 'recording' ? '■ Stop & transcribe' : '● Record command';
    $('record').setAttribute('aria-pressed', String(phase === 'recording'));
    $('cancel-recording').hidden = !['requesting', 'recording', 'transcribing'].includes(phase);
    $('audio-file').disabled = !voice.available || phase !== 'idle';
    $('command-text').disabled = phase !== 'idle';
    $('preview-command').disabled = phase !== 'idle';
    $('apply-command').disabled = phase !== 'idle' || previewText === null;
  }
  function invalidate() { version++; previewText = null; $('apply-command').disabled = true; }
  function releaseMicrophone() {
    if (timer) clearTimeout(timer);
    timer = null;
    stream?.getTracks().forEach(track => track.stop()); stream = null;
  }
  $('command-text').addEventListener('input', () => {
    invalidate(); $('command-preview').textContent = 'Preview your edited command before applying.';
  });
  $('session').addEventListener('input', () => {
    if (phase === 'idle' || phase === 'previewing') {
      invalidate(); $('command-preview').textContent = 'Session settings changed. Preview the command again before applying.';
    }
  });

  async function preview() {
    const text = $('command-text').value.trim();
    invalidate();
    const current = version;
    phase = 'previewing'; controls();
    $('command-preview').textContent = 'Interpreting your request locally…';
    try {
      const result = await api('/api/command/preview', {text, session: readSession()});
      if (current !== version) return;
      $('command-preview').textContent = `${result.command.summary} ${result.command.note || ''}`;
      if (result.command.intent !== 'unknown') previewText = text;
    } catch (error) { if (current === version) $('command-preview').textContent = error.message; }
    finally { phase = 'idle'; controls(); }
  }
  $('command-form').addEventListener('submit', event => { event.preventDefault(); preview(); });
  $('apply-command').addEventListener('click', async () => {
    if (!previewText || phase !== 'idle') return;
    phase = 'applying'; controls();
    try {
      const result = await api('/api/command/apply', {text: previewText, session: readSession()});
      invalidate();
      await applyResult(result);
      $('command-preview').textContent = `Applied: ${result.command.summary}`;
    } catch (error) { $('command-preview').textContent = `Could not apply: ${error.message}`; }
    finally { phase = 'idle'; controls(); }
  });

  async function transcribe(blob) {
    invalidate();
    const current = version;
    if (blob.size === 0 || blob.size > voice.max_bytes) {
      $('voice-status').textContent = 'Choose a nonempty audio recording no larger than 5 MiB.';
      phase = 'idle'; controls(); return;
    }
    phase = 'transcribing'; controls();
    $('voice-status').textContent = 'Transcribing on this device… The first request also loads the speech model.';
    request = new AbortController();
    const timeout = setTimeout(() => request?.abort(), 120000);
    try {
      const response = await fetch('/api/transcribe', {method: 'POST', headers: {'Content-Type': blob.type || 'application/octet-stream'}, body: blob, signal: request.signal});
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Transcription failed');
      if (version !== current) return;
      $('command-text').value = result.text;
      $('voice-status').textContent = `${result.seconds}s recording · ${(result.processing_ms/1000).toFixed(1)}s local processing. Review or edit the transcript below.`;
      await preview();
    } catch (error) {
      if (version === current) $('voice-status').textContent = error.name === 'AbortError' ? 'Transcription timed out. Try a shorter recording or type your command.' : error.message;
    } finally { clearTimeout(timeout); request = null; phase = 'idle'; controls(); }
  }

  $('record').addEventListener('click', async () => {
    if (phase === 'recording') { phase = 'stopping'; controls(); recorder.stop(); return; }
    if (phase !== 'idle') return;
    invalidate();
    const current = version;
    phase = 'requesting'; controls();
    $('voice-status').textContent = 'Waiting for microphone permission…';
    try {
      const acquired = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: true, noiseSuppression: true}, video: false});
      if (version !== current) { acquired.getTracks().forEach(track => track.stop()); return; }
      stream = acquired;
      const mimeType = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = new MediaRecorder(stream, mimeType ? {mimeType} : undefined);
      const parts = []; let bytes = 0;
      discard = false;
      recorder.ondataavailable = event => {
        if (event.data.size) { parts.push(event.data); bytes += event.data.size; }
        if (bytes > voice.max_bytes && recorder.state === 'recording') {
          discard = true; recorder.stop();
          $('voice-status').textContent = 'Recording exceeded the size limit. Try a shorter command.';
        }
      };
      recorder.onstop = () => {
        const type = recorder.mimeType;
        if (version !== current) discard = true;
        releaseMicrophone();
        if (discard) { phase = 'idle'; controls(); return; }
        transcribe(new Blob(parts, {type}));
      };
      recorder.onerror = () => {
        discard = true; releaseMicrophone(); phase = 'idle'; controls();
        $('voice-status').textContent = 'Recording failed. Try another browser or upload an audio file.';
      };
      recorder.start(250);
      phase = 'recording'; controls();
      $('voice-status').textContent = 'Listening… press Stop when done. Automatically stops just before 30 seconds.';
      timer = setTimeout(() => { if (recorder?.state === 'recording') recorder.stop(); }, (voice.max_seconds-1)*1000);
    } catch (error) {
      if (version !== current) return;
      releaseMicrophone(); phase = 'idle'; controls();
      if (version === current) $('voice-status').textContent = error.name === 'NotAllowedError' ? 'Microphone access was denied. Allow it in browser settings, upload a recording, or type your request.' : 'Could not access a microphone. Check the device or upload a recording instead.';
    }
  });
  $('cancel-recording').addEventListener('click', () => {
    invalidate(); discard = true;
    const wasRecording = recorder?.state === 'recording';
    if (wasRecording) recorder.stop();
    request?.abort(); releaseMicrophone();
    phase = wasRecording ? 'stopping' : request ? 'cancelling' : 'idle'; controls();
    $('voice-status').textContent = 'Cancelled. No command was applied.';
  });
  $('audio-file').addEventListener('change', () => {
    const file = $('audio-file').files[0];
    if (file && phase === 'idle') transcribe(file);
    $('audio-file').value = '';
  });
  window.addEventListener('pagehide', () => {
    discard = true; invalidate(); request?.abort();
    if (recorder?.state === 'recording') recorder.stop();
    releaseMicrophone();
  });
  controls();
}
