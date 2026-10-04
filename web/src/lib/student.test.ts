// Python/browser parity for the distilled student: the same weights must give the same answers.
import fixture from '../../../tests/fixtures/student-parity.json';
import { type StudentModel, crc32, predict } from './student';

const model = fixture.model as unknown as StudentModel;

test('crc32 matches zlib', () => {
  expect(crc32('space')).toBe(695386426);
  expect(crc32('brûlée')).toBe(3698597479);
  expect(crc32('')).toBe(0);
  expect(crc32('123456789')).toBe(0xcbf43926);
});

test('browser predictions match Python to 1e-9', () => {
  for (const { state, probabilities } of fixture.cases) {
    // plain strings and non-ASCII film-state objects
    const { answers } = predict(model, state);
    for (const [qid, expected] of Object.entries(probabilities as Record<string, Record<string, number>>)) {
      const answer = answers[qid];
      if (!answer) throw new Error(`no answer for ${qid}`);
      const got: Record<string, number> =
        answer.type === 'noul' ? { false: 1 - answer.noul, true: answer.noul } : answer.probabilities;
      for (const [option, p] of Object.entries(expected)) {
        expect(Math.abs((got[option] ?? Number.NaN) - p)).toBeLessThan(1e-9);
      }
    }
  }
});

test('rejects bad input and unknown formats', () => {
  expect(() => predict(model, '')).toThrow();
  expect(() => predict({ ...model, format: 'other' } as unknown as StudentModel, 'x')).toThrow();
});
