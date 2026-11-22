#!/usr/bin/env python3
"""Gera os áudios listados em app/audio_manifest.json usando as vozes do macOS.

Uso:  python3 curso/fonte/gerar_audio.py [--force]

- Usa `say` (síntese de voz do macOS) e `afconvert` (conversão para AAC/.m4a).
- Faixas com "parts" (diálogos e listenings completos) são a concatenação das falas,
  com uma pausa curta entre elas, mantendo a voz de cada personagem.
- Só gera o que ainda não existe; use --force para regerar tudo.
- As vozes são de qualidade "sistema". Para produção, você pode trocar por um serviço
  de TTS profissional (ou gravações reais) usando o mesmo manifesto: file, text, voice.
"""
import json
import subprocess
import sys
import tempfile
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
MANIFEST = RAIZ / "app" / "audio_manifest.json"
RATE = 22050
PAUSE_SEC = 0.6
TMP = Path(tempfile.mkdtemp(prefix="wisdome-audio-"))


def wav_path(file):
    return TMP / (file.replace("/", "__") + ".wav")


def synth(entry):
    wav = wav_path(entry["file"])
    subprocess.run(["say", "-v", entry["voice"], "-r", "165", "-o", str(wav),
                    "--file-format=WAVE", f"--data-format=LEI16@{RATE}", entry["text"]], check=True)
    return wav


def concat(parts, out):
    silence = b"\x00\x00" * int(RATE * PAUSE_SEC)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        for i, p in enumerate(parts):
            with wave.open(str(p), "rb") as r:
                w.writeframes(r.readframes(r.getnframes()))
            if i < len(parts) - 1:
                w.writeframes(silence)


def to_m4a(wav, file):
    out = RAIZ / file
    out.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["afconvert", "-f", "m4af", "-d", "aac", "-b", "64000", str(wav), str(out)], check=True)


def main():
    force = "--force" in sys.argv
    entries = json.loads(MANIFEST.read_text())
    simple = [e for e in entries if "parts" not in e]
    combo = [e for e in entries if "parts" in e]
    by_file = {e["file"]: e for e in simple}
    todo_combo = [e for e in combo if force or not (RAIZ / e["file"]).exists()]
    need = {p for e in todo_combo for p in e["parts"]}
    todo_simple = [e for e in simple if force or not (RAIZ / e["file"]).exists() or e["file"] in need]

    def do_simple(e):
        wav = synth(e)
        if force or not (RAIZ / e["file"]).exists():
            to_m4a(wav, e["file"])

    with ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(do_simple, todo_simple))
    for e in todo_combo:
        out = TMP / (e["file"].replace("/", "__") + ".wav")
        concat([wav_path(by_file[p]["file"]) for p in e["parts"]], out)
        to_m4a(out, e["file"])
    print(f"OK: {len(todo_simple)} faixas simples e {len(todo_combo)} faixas completas geradas em {RAIZ / 'audio'}")


if __name__ == "__main__":
    main()
