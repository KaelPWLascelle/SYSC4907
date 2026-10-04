/**
 * Speech capture and command review, as a framework-free state machine (React subscribes via
 * useSyncExternalStore). Nothing is applied without an explicit preview -> apply. No browser or cloud
 * speech-recognition service: audio goes to the local /api/transcribe only.
 *
 * Every async step captures `version`; anything that invalidates (editing, cancelling, a new
 * recording) bumps it, so late results are dropped instead of overwriting newer state.
 */
import type { CommandResponse, Session, TranscribeResponse, VoiceStatus } from '../../api/types';

export type Phase =
  'idle' | 'requesting' | 'recording' | 'stopping' | 'transcribing' | 'cancelling' | 'previewing' | 'applying';

export interface CommandSnapshot {
  phase: Phase;
  text: string;
  /** What the assistant understood, or why it could not. */
  message: string;
  /** Microphone / transcription status. */
  voiceStatus: string;
  /** A successful preview exists for the current text and scene. */
  canApply: boolean;
}

export interface CommandDeps {
  voice: VoiceStatus;
  /** The scene commands are interpreted against; keep it current with setSession(). */
  session: Session;
  preview: (text: string, session: Session) => Promise<CommandResponse>;
  apply: (text: string, session: Session) => Promise<CommandResponse>;
  transcribe: (audio: Blob, signal: AbortSignal) => Promise<TranscribeResponse>;
  onApplied: (result: CommandResponse) => void | Promise<void>;
  /** Injected for tests; defaults to the browser's. */
  media?: { getUserMedia?: MediaDevices['getUserMedia']; MediaRecorder?: typeof MediaRecorder };
}

export const DEFAULT_MESSAGE = 'Try “Like Arrival”, “no horror, 90 minutes”, or “Clear my rating for Alien”.';
const TRANSCRIBE_TIMEOUT_MS = 120_000;
const RECORDER_TYPES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4'];

const errorName = (error: unknown) => (error instanceof Error || error instanceof DOMException ? error.name : '');
const errorMessage = (error: unknown) => (error instanceof Error ? error.message : String(error));

export class CommandController {
  readonly canRecord: boolean;
  private snapshot: CommandSnapshot;
  private readonly listeners = new Set<() => void>();
  private readonly getUserMedia?: MediaDevices['getUserMedia'];
  private readonly Recorder?: typeof MediaRecorder;
  private recorder: MediaRecorder | null = null;
  private stream: MediaStream | null = null;
  private timer: ReturnType<typeof setTimeout> | null = null;
  private request: AbortController | null = null;
  private discard = false;
  private version = 0;
  private previewText: string | null = null;
  private session: Session;

  constructor(private readonly deps: CommandDeps) {
    const media = deps.media ?? {
      getUserMedia: globalThis.navigator?.mediaDevices?.getUserMedia?.bind(globalThis.navigator.mediaDevices),
      MediaRecorder: globalThis.MediaRecorder,
    };
    this.getUserMedia = media.getUserMedia;
    this.Recorder = media.MediaRecorder;
    this.session = deps.session;
    const supported = Boolean(this.getUserMedia && this.Recorder);
    this.canRecord = deps.voice.available && supported;
    this.snapshot = {
      phase: 'idle',
      text: '',
      message: DEFAULT_MESSAGE,
      canApply: false,
      voiceStatus:
        deps.voice.message +
        (supported ? '' : ' Microphone capture is unavailable in this browser; use a recording file.'),
    };
  }

  // ---------- store protocol ----------
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  getSnapshot = () => this.snapshot;

  private update(patch: Partial<CommandSnapshot>) {
    this.snapshot = { ...this.snapshot, ...patch, canApply: this.previewText !== null };
    this.listeners.forEach(listener => listener());
  }

  private invalidate() {
    this.version++;
    this.previewText = null;
  }

  private releaseMicrophone() {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    this.stream?.getTracks().forEach(track => track.stop());
    this.stream = null;
  }

  // ---------- typed commands ----------
  setText(text: string) {
    this.invalidate();
    this.update({ text, message: 'Preview your edited command before applying.' });
  }

  /** The scene changed. A previewed command was interpreted against the old one, so it must be previewed again. */
  setSession(session: Session) {
    if (session === this.session) return;
    this.session = session;
    if (this.previewText === null && this.snapshot.phase !== 'previewing') return;
    this.invalidate();
    this.update({ message: 'Your scene changed. Preview the command again before applying.' });
  }

  async preview() {
    const text = this.snapshot.text.trim();
    this.invalidate();
    if (!text) {
      this.update({ message: 'Type or say a request first.' });
      return;
    }
    const current = this.version;
    this.update({ phase: 'previewing', message: 'Interpreting your request locally…' });
    try {
      const { command } = await this.deps.preview(text, this.session);
      if (current !== this.version) return;
      if (command.intent !== 'unknown') this.previewText = text;
      this.update({ message: `${command.summary} ${command.note ?? ''}`.trim() });
    } catch (error) {
      if (current === this.version) this.update({ message: errorMessage(error) });
    } finally {
      this.update({ phase: 'idle' });
    }
  }

  async apply() {
    const text = this.previewText;
    if (text === null || this.snapshot.phase !== 'idle') return;
    this.update({ phase: 'applying' });
    try {
      const result = await this.deps.apply(text, this.session);
      this.invalidate();
      await this.deps.onApplied(result);
      this.update({ message: `Applied: ${result.command.summary}` });
    } catch (error) {
      this.update({ message: `Could not apply: ${errorMessage(error)}` });
    } finally {
      this.update({ phase: 'idle' });
    }
  }

  // ---------- voice ----------
  async transcribe(audio: Blob) {
    this.invalidate();
    const current = this.version;
    if (audio.size === 0 || audio.size > this.deps.voice.max_bytes) {
      this.update({ phase: 'idle', voiceStatus: 'Choose a nonempty audio recording no larger than 5 MiB.' });
      return;
    }
    const request = new AbortController();
    this.request = request;
    this.update({
      phase: 'transcribing',
      voiceStatus: 'Transcribing on this device… The first request also loads the speech model.',
    });
    const timeout = setTimeout(() => request.abort(), TRANSCRIBE_TIMEOUT_MS);
    try {
      const result = await this.deps.transcribe(audio, request.signal);
      if (current !== this.version) return;
      this.update({
        text: result.text,
        voiceStatus: `${result.seconds}s recording · ${(result.processing_ms / 1000).toFixed(1)}s local processing. Review or edit the transcript.`,
      });
      await this.preview();
    } catch (error) {
      if (current === this.version) {
        this.update({
          voiceStatus:
            errorName(error) === 'AbortError'
              ? 'Transcription timed out. Try a shorter recording or type your command.'
              : errorMessage(error),
        });
      }
    } finally {
      clearTimeout(timeout);
      if (this.request === request) this.request = null;
      this.update({ phase: 'idle' });
    }
  }

  transcribeFile(file: File) {
    if (this.snapshot.phase === 'idle') void this.transcribe(file);
  }

  async toggleRecord() {
    if (this.snapshot.phase === 'recording') {
      this.update({ phase: 'stopping' });
      this.recorder?.stop();
      return;
    }
    if (this.snapshot.phase !== 'idle' || !this.canRecord || !this.getUserMedia || !this.Recorder) return;
    this.invalidate();
    const current = this.version;
    this.update({ phase: 'requesting', voiceStatus: 'Waiting for microphone permission…' });
    try {
      const acquired = await this.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (current !== this.version) {
        acquired.getTracks().forEach(track => track.stop()); // cancelled while the prompt was open
        return;
      }
      this.stream = acquired;
      this.startRecorder(acquired, current);
    } catch (error) {
      if (current !== this.version) return;
      this.releaseMicrophone();
      this.update({
        phase: 'idle',
        voiceStatus:
          errorName(error) === 'NotAllowedError'
            ? 'Microphone access was denied. Allow it in browser settings, upload a recording, or type your request.'
            : 'Could not access a microphone. Check the device or upload a recording instead.',
      });
    }
  }

  private startRecorder(stream: MediaStream, current: number) {
    const Recorder = this.Recorder;
    if (!Recorder) return;
    const mimeType = RECORDER_TYPES.find(type => Recorder.isTypeSupported(type));
    const recorder = new Recorder(stream, mimeType ? { mimeType } : undefined);
    this.recorder = recorder;
    const parts: Blob[] = [];
    let bytes = 0;
    this.discard = false;
    recorder.ondataavailable = event => {
      if (event.data.size) {
        parts.push(event.data);
        bytes += event.data.size;
      }
      if (bytes > this.deps.voice.max_bytes && recorder.state === 'recording') {
        this.discard = true;
        recorder.stop();
        this.update({ voiceStatus: 'Recording exceeded the size limit. Try a shorter command.' });
      }
    };
    recorder.onstop = () => {
      if (current !== this.version) this.discard = true;
      this.releaseMicrophone();
      if (this.discard) {
        this.update({ phase: 'idle' });
        return;
      }
      void this.transcribe(new Blob(parts, { type: recorder.mimeType }));
    };
    recorder.onerror = () => {
      this.discard = true;
      this.releaseMicrophone();
      this.update({ phase: 'idle', voiceStatus: 'Recording failed. Try another browser or upload an audio file.' });
    };
    recorder.start(250);
    this.update({
      phase: 'recording',
      voiceStatus: 'Listening… press Stop when done. Automatically stops just before 30 seconds.',
    });
    this.timer = setTimeout(
      () => {
        if (recorder.state === 'recording') recorder.stop();
      },
      (this.deps.voice.max_seconds - 1) * 1000,
    );
  }

  cancel() {
    this.invalidate();
    this.discard = true;
    const wasRecording = this.recorder?.state === 'recording';
    if (wasRecording) this.recorder?.stop();
    const transcribing = this.request !== null;
    this.request?.abort();
    this.releaseMicrophone();
    this.update({
      phase: wasRecording ? 'stopping' : transcribing ? 'cancelling' : 'idle',
      voiceStatus: 'Cancelled. No command was applied.',
    });
  }

  /** Leaving the page: stop the microphone and drop anything in flight. */
  dispose() {
    this.discard = true;
    this.invalidate();
    this.request?.abort();
    if (this.recorder?.state === 'recording') this.recorder.stop();
    this.releaseMicrophone();
  }
}
