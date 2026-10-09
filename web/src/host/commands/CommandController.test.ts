// State-machine tests with a fake microphone and recorder. No real audio or network.
import type { CommandResponse, VoiceStatus } from '../../api/types';
import { CommandController, type CommandDeps } from './CommandController';

const flush = () => new Promise(resolve => setTimeout(resolve, 0));
const SESSION = {
  mood: 'any' as const,
  minutes: 120,
  intensity: 0.5,
  novelty: 0.3,
  excluded_genres: [],
  medium: 'any' as const,
  playable: false,
};
const LIKE: CommandResponse = {
  command: { intent: 'feedback', summary: 'Like Arrival', id: 'm001', value: 1 },
  session: SESSION,
  feedback: {},
};

function setup(
  overrides: Partial<CommandDeps> & { available?: boolean; getUserMedia?: () => Promise<MediaStream> } = {},
) {
  let stopped = 0;
  const stream = { getTracks: () => [{ stop: () => stopped++ }] } as unknown as MediaStream;
  class FakeRecorder {
    static isTypeSupported() {
      return true;
    }
    state: RecordingState = 'inactive';
    mimeType = 'audio/webm';
    ondataavailable: ((event: BlobEvent) => void) | null = null;
    onstop: (() => void) | null = null;
    onerror: (() => void) | null = null;
    start() {
      this.state = 'recording';
    }
    stop() {
      this.state = 'inactive';
      queueMicrotask(() => {
        this.ondataavailable?.({ data: new Blob(['audio']) } as BlobEvent);
        this.onstop?.();
      });
    }
  }
  const voice: VoiceStatus = {
    available: overrides.available ?? true,
    message: 'Test',
    max_bytes: 100,
    max_seconds: 30,
  };
  const calls = { preview: 0, apply: 0, transcribe: 0, applied: 0 };
  const controller = new CommandController({
    voice,
    session: SESSION,
    preview: overrides.preview ?? (async () => (calls.preview++, LIKE)),
    apply: overrides.apply ?? (async () => (calls.apply++, LIKE)),
    transcribe:
      overrides.transcribe ??
      (async () => (calls.transcribe++, { text: 'Like Arrival', seconds: 2, processing_ms: 50 })),
    onApplied: () => {
      calls.applied++;
    },
    media: {
      getUserMedia: (overrides.getUserMedia ?? (async () => stream)) as MediaDevices['getUserMedia'],
      MediaRecorder: FakeRecorder as unknown as typeof MediaRecorder,
    },
  });
  return { controller, calls, stream, stopped: () => stopped, state: () => controller.getSnapshot() };
}

test('typed preview then apply works without voice', async () => {
  const ui = setup({ available: false });
  expect(ui.controller.canRecord).toBe(false);
  ui.controller.setText('Like Arrival');
  await ui.controller.preview();
  expect(ui.calls.applied).toBe(0);
  expect(ui.state().canApply).toBe(true);
  await ui.controller.apply();
  expect(ui.calls.applied).toBe(1);
  expect(ui.state().canApply).toBe(false);
  expect(ui.state().message).toBe('Applied: Like Arrival');
});

test('editing the text or the scene invalidates a preview', async () => {
  const ui = setup();
  ui.controller.setText('Like Arrival');
  await ui.controller.preview();
  ui.controller.setText('Like Arrival!');
  await ui.controller.apply();
  expect(ui.calls.apply).toBe(0);

  await ui.controller.preview();
  ui.controller.setSession({ ...SESSION, mood: 'tense' });
  expect(ui.state().canApply).toBe(false);
  expect(ui.state().message).toMatch(/scene changed/);
});

test('a scene change with nothing previewed leaves the message alone', () => {
  const ui = setup();
  ui.controller.setSession({ ...SESSION, mood: 'tense' });
  expect(ui.state().message).toMatch(/Try/);
});

test('empty and unknown commands never enable apply', async () => {
  const ui = setup({
    preview: async () => ({ ...LIKE, command: { intent: 'unknown', summary: 'Unknown' } }),
  });
  await ui.controller.preview();
  expect(ui.state().message).toMatch(/first/);
  ui.controller.setText('Like it');
  await ui.controller.preview();
  expect(ui.state().canApply).toBe(false);
});

test('a stale preview result is dropped', async () => {
  let resolve: (value: CommandResponse) => void = () => {};
  const ui = setup({ preview: () => new Promise(r => (resolve = r)) });
  ui.controller.setText('Like Arrival');
  const pending = ui.controller.preview();
  ui.controller.setText('something else');
  resolve(LIKE);
  await pending;
  expect(ui.state().canApply).toBe(false);
  expect(ui.state().message).toMatch(/Preview your edited/);
});

test('permission denial restores the controls', async () => {
  const ui = setup({
    getUserMedia: async () => {
      throw Object.assign(new Error(), { name: 'NotAllowedError' });
    },
  });
  await ui.controller.toggleRecord();
  expect(ui.state().voiceStatus).toMatch(/denied/);
  expect(ui.state().phase).toBe('idle');
  expect(ui.calls.transcribe).toBe(0);
});

test('cancelling a pending permission request stops late-arriving tracks', async () => {
  let resolve: (stream: MediaStream) => void = () => {};
  const ui = setup({ getUserMedia: () => new Promise(r => (resolve = r)) });
  const start = ui.controller.toggleRecord();
  ui.controller.cancel();
  resolve(ui.stream);
  await start;
  expect(ui.stopped()).toBe(1);
  expect(ui.calls.transcribe).toBe(0);
});

test('record then stop transcribes and previews, but does not apply', async () => {
  const ui = setup();
  await ui.controller.toggleRecord();
  expect(ui.state().phase).toBe('recording');
  expect(ui.stopped()).toBe(0);
  await ui.controller.toggleRecord();
  await flush();
  expect(ui.stopped()).toBe(1);
  expect(ui.calls.transcribe).toBe(1);
  expect(ui.state().text).toBe('Like Arrival');
  expect(ui.calls.applied).toBe(0);
  expect(ui.state().canApply).toBe(true);
});

test('cancelling a recording releases the microphone without uploading', async () => {
  const ui = setup();
  await ui.controller.toggleRecord();
  ui.controller.cancel();
  await flush();
  expect(ui.stopped()).toBe(1);
  expect(ui.calls.transcribe).toBe(0);
  expect(ui.state().phase).toBe('idle');
});

test('oversized files are rejected before upload', async () => {
  const ui = setup();
  ui.controller.transcribeFile(new File(['x'.repeat(101)], 'big.webm'));
  await flush();
  expect(ui.calls.transcribe).toBe(0);
  expect(ui.state().voiceStatus).toMatch(/no larger/);
});

test('cancelling transcription neither previews nor applies a stale result', async () => {
  const ui = setup({
    transcribe: (_audio, signal) =>
      new Promise((_resolve, reject) =>
        signal.addEventListener('abort', () => reject(Object.assign(new Error(), { name: 'AbortError' }))),
      ),
  });
  ui.controller.transcribeFile(new File(['audio'], 'clip.webm'));
  ui.controller.cancel();
  await flush();
  expect(ui.calls.preview).toBe(0);
  expect(ui.calls.applied).toBe(0);
  expect(ui.state().phase).toBe('idle');
  expect(ui.state().voiceStatus).toMatch(/Cancelled/);
});

test('dispose releases the microphone', async () => {
  const ui = setup();
  await ui.controller.toggleRecord();
  ui.controller.dispose();
  await flush();
  expect(ui.stopped()).toBe(1);
  expect(ui.calls.transcribe).toBe(0);
});
