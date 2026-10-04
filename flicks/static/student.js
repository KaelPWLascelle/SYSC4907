/** In-browser inference for a student distilled by `python -m flicks.distill`.
 * Mirrors flicks/distill.py exactly (tokens, crc32 feature hashing, softmax) so the same JSON
 * weights give the same answers in Python and in the browser. No network, no dependencies.
 * Returns the /v1/systemone wire format, so callers validate it like any other backend. */

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

export function crc32(text) {
  let crc = 0xffffffff;
  for (const byte of new TextEncoder().encode(text)) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

export function tokens(text) {
  const words = text.toLowerCase().match(/[a-z0-9]+/g) || [];
  return [...new Set(words.map(w => (w.length > 3 && w.endsWith('s') ? w.slice(0, -1) : w)))].sort();
}

/** Mirrors systemone.state_text: strings as-is, objects as compact JSON with real characters. */
export function stateText(state) { return typeof state === 'string' ? state : JSON.stringify(state); }

export function features(state, dim) {
  const text = stateText(state);
  const counts = new Map();
  for (const word of tokens(text)) {
    const index = crc32(word) % dim;
    counts.set(index, (counts.get(index) || 0) + 1);
  }
  const norm = Math.sqrt([...counts.values()].reduce((s, v) => s + v * v, 0)) || 1;
  return new Map([...counts].map(([i, v]) => [i, v / norm]));
}

function optionKeys(question) {
  if (question.type === 'choice') return Object.keys(question.criteria);
  if (question.type === 'score') return question.criteria.map((_, i) => String(i));
  return ['false', 'true'];
}

export function predict(model, state) {
  if (model.format !== 'hashed-bow-v1') throw new Error('Unknown student format');
  const text = stateText(state);
  if (typeof text !== 'string' || !text.trim() || text.length > 50000) throw new Error('State must be 1-50000 characters');
  const x = features(text, model.dim);
  const answers = {};
  for (const [qid, question] of Object.entries(model.questions)) {
    const logits = model.weights[qid].map((w, k) => {
      let sum = model.bias[qid][k];
      for (const [i, v] of x) sum += (w[String(i)] || 0) * v;
      return sum;
    });
    const top = Math.max(...logits);
    const exp = logits.map(v => Math.exp(v - top));
    const total = exp.reduce((a, b) => a + b, 0);
    const probs = Object.fromEntries(optionKeys(question).map((key, k) => [key, exp[k] / total]));
    answers[qid] = question.type === 'noul' ? {type: 'noul', noul: probs.true} : {type: question.type, probabilities: probs};
  }
  return {model: 'flicks-student', answers};
}
