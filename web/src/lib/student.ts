/**
 * In-browser inference for a student distilled by `python -m flicks.distill`.
 * Mirrors flicks/distill.py exactly (tokens, crc32 feature hashing, softmax) so the same JSON
 * weights give the same answers in Python and in the browser. No network, no dependencies.
 * Returns the /v1/systemone wire format, so callers validate it like any other backend.
 */

type Question =
  | { type: 'choice'; criteria: Record<string, string> }
  | { type: 'score'; criteria: string[] }
  | { type: 'noul'; criteria?: Record<string, string> };

export interface StudentModel {
  format: 'hashed-bow-v1';
  dim: number;
  questions: Record<string, Question>;
  weights: Record<string, Record<string, number>[]>;
  bias: Record<string, number[]>;
}

export type Answer =
  { type: 'noul'; noul: number } | { type: 'choice' | 'score'; probabilities: Record<string, number> };

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(text: string): number {
  let crc = 0xffffffff;
  for (const byte of new TextEncoder().encode(text)) crc = (CRC_TABLE[(crc ^ byte) & 0xff] ?? 0) ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export function tokens(text: string): string[] {
  const words = text.toLowerCase().match(/[a-z0-9]+/g) ?? [];
  return [...new Set(words.map(w => (w.length > 3 && w.endsWith('s') ? w.slice(0, -1) : w)))].sort();
}

/** Mirrors systemone.state_text: strings as-is, objects as compact JSON with real characters. */
export const stateText = (state: unknown): string => (typeof state === 'string' ? state : JSON.stringify(state));

export function features(state: unknown, dim: number): Map<number, number> {
  const counts = new Map<number, number>();
  for (const word of tokens(stateText(state))) {
    const index = crc32(word) % dim;
    counts.set(index, (counts.get(index) ?? 0) + 1);
  }
  const norm = Math.sqrt([...counts.values()].reduce((sum, v) => sum + v * v, 0)) || 1;
  return new Map([...counts].map(([i, v]) => [i, v / norm]));
}

export function optionKeys(question: Question): string[] {
  if (question.type === 'choice') return Object.keys(question.criteria);
  if (question.type === 'score') return question.criteria.map((_, i) => String(i));
  return ['false', 'true'];
}

/** Class probabilities for one question, in optionKeys order. */
export function distribution(model: StudentModel, qid: string, x: Map<number, number>): number[] {
  const weights = model.weights[qid];
  const bias = model.bias[qid];
  if (!weights || !bias) throw new Error(`The student has no weights for question ${qid}`);
  const logits = weights.map((w, k) => {
    let sum = bias[k] ?? 0;
    for (const [i, v] of x) sum += (w[String(i)] ?? 0) * v;
    return sum;
  });
  const top = Math.max(...logits);
  const exp = logits.map(v => Math.exp(v - top));
  const total = exp.reduce((a, b) => a + b, 0);
  return exp.map(v => v / total);
}

export function predict(
  model: StudentModel,
  state: unknown,
): { model: 'flicks-student'; answers: Record<string, Answer> } {
  if (model.format !== 'hashed-bow-v1') throw new Error('Unknown student format');
  const text = stateText(state);
  if (!text.trim() || text.length > 50000) throw new Error('State must be 1-50000 characters');
  const x = features(text, model.dim);
  const answers: Record<string, Answer> = {};
  for (const [qid, question] of Object.entries(model.questions)) {
    const p = distribution(model, qid, x);
    const probs = Object.fromEntries(optionKeys(question).map((key, k) => [key, p[k] ?? 0]));
    answers[qid] =
      question.type === 'noul'
        ? { type: 'noul', noul: probs.true ?? 0 }
        : { type: question.type, probabilities: probs };
  }
  return { model: 'flicks-student', answers };
}
