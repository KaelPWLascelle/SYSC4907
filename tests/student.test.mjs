// Python/browser parity for the distilled student: same weights must give the same answers.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
const source = readFileSync(new URL('../flicks/static/student.js', import.meta.url), 'utf8');
const {predict, crc32} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const fixture = JSON.parse(readFileSync(new URL('./fixtures/student-parity.json', import.meta.url), 'utf8'));

test('crc32 matches zlib', () => {
  assert.equal(crc32('space'), 695386426);
  assert.equal(crc32('brûlée'), 3698597479);
  assert.equal(crc32(''), 0);
  assert.equal(crc32('123456789'), 0xcbf43926);
});

test('browser predictions match Python to 1e-9', () => {
  for (const {state, probabilities} of fixture.cases) {  // plain strings and non-ASCII film-state objects
    const {answers} = predict(fixture.model, state);
    for (const [qid, expected] of Object.entries(probabilities)) {
      const got = answers[qid].type === 'noul' ? {false: 1 - answers[qid].noul, true: answers[qid].noul} : answers[qid].probabilities;
      for (const [option, p] of Object.entries(expected)) assert.ok(Math.abs(got[option] - p) < 1e-9, `${JSON.stringify(state)} ${qid} ${option}`);
    }
  }
});

test('rejects bad input and unknown formats', () => {
  assert.throws(() => predict(fixture.model, ''));
  assert.throws(() => predict({...fixture.model, format: 'other'}, 'x'));
});
