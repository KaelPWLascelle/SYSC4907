"""Explicit one-time model download; Kevin never downloads during transcription."""
import argparse
import hashlib
import json
from pathlib import Path
from huggingface_hub import snapshot_download


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['tiny.en', 'base.en'], default='base.en')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--revision', help='Override the pinned upstream model revision')
    args = parser.parse_args()
    repo = f'Systran/faster-whisper-{args.model}'
    args.output = args.output or Path(f'.local/models/whisper-{args.model}')
    revision = args.revision or {'tiny.en': '0d3d19a32d3338f10357c0889762bd8d64bbdeba', 'base.en': '3d3d5dee26484f91867d81cb899cfcf72b96be6c'}[args.model]
    snapshot_download(repo, revision=revision, local_dir=args.output,
                      allow_patterns=['model.bin', 'config.json', 'tokenizer.json', 'vocabulary.*', 'preprocessor_config.json', 'README.md'])
    files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.output.iterdir() if p.is_file() and p.name != 'kevin-model.json'}
    (args.output/'kevin-model.json').write_text(json.dumps({'repository': repo, 'revision': revision, 'sha256': files}, indent=2)+'\n')
    print(f'Voice model ready: {args.output.resolve()}')

if __name__ == '__main__':
    main()
