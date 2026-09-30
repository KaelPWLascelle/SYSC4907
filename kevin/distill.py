"""Distil a System One teacher's catalogue tags into a small student that runs anywhere.

Two outputs from one tag file:

1. ``--export-laya DIR``: train/dev/test JSONL in the row schema Laya's fine-tuning notebook reads
   (``state``, ``questions``, ``gold`` = teacher probabilities). This is the path to a real
   open-weights movie decision model, trained on free Kaggle T4 GPUs.
2. ``--student FILE``: a dependency-free soft-label softmax regression over hashed words. It is a
   baseline and a working stand-in: it speaks the same wire format, is a few hundred KB of JSON,
   and its predict step is a sparse dot product that ports to TypeScript in ~30 lines.

    python -m kevin.distill --tags work/tags.json --export-laya work/laya-data --student work/student.json
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import mean
import zlib
from .core import load_catalog
from .systemone import options, state_text, tokens, validate_questions
from .tagging import film_state, load_tags

FEATURES = 'hashed-bow-v1'


def split_of(content_id):
    """Stable 70/10/20 split by ID hash, so re-tagging never leaks titles across splits."""
    bucket = int(hashlib.sha1(content_id.encode()).hexdigest(), 16) % 10
    return 'train' if bucket < 7 else 'dev' if bucket == 7 else 'test'


def export_laya(catalog, data, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    files = {name: (out_dir/f'{name}.jsonl').open('w', encoding='utf-8') for name in ('train', 'dev', 'test')}
    counts = dict.fromkeys(files, 0)
    try:
        for item in catalog:
            tag = data['tags'].get(item.id)
            if not tag:
                continue
            row = {'id': item.id, 'state': json.dumps(film_state(item), ensure_ascii=False),
                   'questions': data['questions'], 'gold': {qid: t['probabilities'] for qid, t in tag.items()}}
            name = split_of(item.id)
            files[name].write(json.dumps(row, ensure_ascii=False) + '\n')
            counts[name] += 1
    finally:
        for handle in files.values():
            handle.close()
    (out_dir/'README.md').write_text(
        f'Teacher: {data["backend"]}\nCreated: {data["created"]}\nQuestions sha256: {data["questions_sha256"]}\n'
        f'Rows: {json.dumps(counts)}\nSplit: sha1(id) % 10 -> 0-6 train, 7 dev, 8-9 test.\n'
        'Gold = teacher probabilities (soft targets), not human labels.\n', encoding='utf-8')
    return counts


def features(state, dim):
    words = sorted(tokens(state_text(state)))
    counts = {}
    for word in words:
        index = zlib.crc32(word.encode()) % dim
        counts[index] = counts.get(index, 0) + 1.0
    norm = math.sqrt(sum(v * v for v in counts.values())) or 1.0
    return {i: v / norm for i, v in counts.items()}


def softmax(logits):
    top = max(logits)
    exp = [math.exp(v - top) for v in logits]
    total = sum(exp)
    return [v / total for v in exp]


class Student:
    """Per-question multinomial logistic regression. Also a System One backend (local=True)."""
    local = True

    def __init__(self, questions, dim=4096, weights=None, meta=None):
        self.questions, self.dim = validate_questions(questions), dim
        self.weights = weights or {qid: [dict() for _ in options(q)] for qid, q in questions.items()}
        self.bias = {qid: [0.0] * len(options(q)) for qid, q in questions.items()}
        self.meta = meta or {}
        self.name = f'distilled student ({self.meta.get("teacher", "unknown teacher")})'

    def distribution(self, qid, x):
        logits = [self.bias[qid][k] + sum(w.get(i, 0.0) * v for i, v in x.items())
                  for k, w in enumerate(self.weights[qid])]
        return softmax(logits)

    def fit(self, rows, epochs=300, lr=0.5, l2=1e-3):
        """Full-batch gradient descent on soft cross-entropy: rows are (state, {qid: probs})."""
        data = [(features(state, self.dim), gold) for state, gold in rows]
        for qid, q in self.questions.items():
            keys = options(q)
            items = [(x, [gold[qid][k] for k in keys]) for x, gold in data if qid in gold]
            if not items:
                continue
            for _ in range(epochs):
                grads = [dict() for _ in keys]
                bias_grad = [0.0] * len(keys)
                for x, target in items:
                    p = self.distribution(qid, x)
                    for k in range(len(keys)):
                        delta = (p[k] - target[k]) / len(items)
                        bias_grad[k] += delta
                        for i, v in x.items():
                            grads[k][i] = grads[k].get(i, 0.0) + delta * v
                for k, weight in enumerate(self.weights[qid]):
                    self.bias[qid][k] -= lr * bias_grad[k]
                    for i in set(weight) | set(grads[k]):
                        value = weight.get(i, 0.0) * (1 - lr * l2) - lr * grads[k].get(i, 0.0)
                        if abs(value) > 1e-6:
                            weight[i] = value
                        else:
                            weight.pop(i, None)
        return self

    def raw(self, state, questions):
        if questions != self.questions:
            raise ValueError('This student only answers the questions it was trained on')
        x, answers = features(state, self.dim), {}
        for qid, q in questions.items():
            probs = dict(zip(options(q), (round(p, 6) for p in self.distribution(qid, x))))
            answers[qid] = {'type': 'noul', 'noul': probs['true']} if q['type'] == 'noul' else {'type': q['type'], 'probabilities': probs}
        return {'model': 'kevin-student', 'answers': answers}

    def to_json(self):
        return {'format': FEATURES, 'dim': self.dim, 'meta': self.meta, 'questions': self.questions,
                'bias': self.bias, 'weights': {qid: [{str(i): round(v, 6) for i, v in w.items()} for w in ws]
                                               for qid, ws in self.weights.items()}}

    @classmethod
    def from_json(cls, data):
        if data.get('format') != FEATURES:
            raise ValueError('Unknown student format')
        weights = {qid: [{int(i): float(v) for i, v in w.items()} for w in ws] for qid, ws in data['weights'].items()}
        student = cls(data['questions'], data['dim'], weights, data.get('meta'))
        student.bias = {qid: [float(b) for b in bs] for qid, bs in data['bias'].items()}
        return student


def agreement(student, catalog, data, split):
    """How often the student's top answer matches the teacher's, and mean KL(teacher || student)."""
    top, kl = [], []
    for item in catalog:
        tag = data['tags'].get(item.id)
        if not tag or split_of(item.id) != split:
            continue
        x = features(film_state(item), student.dim)
        for qid, q in student.questions.items():
            keys, teacher = options(q), tag[qid]['probabilities']
            p = student.distribution(qid, x)
            top.append(keys[p.index(max(p))] == max(keys, key=lambda k: teacher[k]))
            kl.append(sum(teacher[k] * math.log(max(teacher[k], 1e-9) / max(p[i], 1e-9)) for i, k in enumerate(keys)))
    return {'split': split, 'decisions': len(top), 'top1_agreement': round(mean(top), 3) if top else None,
            'mean_kl': round(mean(kl), 4) if kl else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description='Export teacher tags and distil a student')
    parser.add_argument('--catalog', type=Path, default=Path(__file__).parent/'data'/'movies.json')
    parser.add_argument('--tags', type=Path, required=True)
    parser.add_argument('--export-laya', type=Path)
    parser.add_argument('--student', type=Path, help='Train the hashed-BoW student and write it here')
    parser.add_argument('--dim', type=int, default=4096)
    args = parser.parse_args(argv)
    catalog = load_catalog(args.catalog)
    data = load_tags(args.tags, catalog)
    report = {'teacher': data['backend']}
    if args.export_laya:
        report['laya_rows'] = export_laya(catalog, data, args.export_laya)
    if args.student:
        rows = [(film_state(item), {q: t['probabilities'] for q, t in data['tags'][item.id].items()})
                for item in catalog if item.id in data['tags'] and split_of(item.id) == 'train']
        student = Student(data['questions'], args.dim, meta={'teacher': data['backend'],
                                                              'questions_sha256': data['questions_sha256']}).fit(rows)
        args.student.parent.mkdir(parents=True, exist_ok=True)
        args.student.write_text(json.dumps(student.to_json()) + '\n', encoding='utf-8')
        report['student'] = [agreement(student, catalog, data, s) for s in ('train', 'dev', 'test')]
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
