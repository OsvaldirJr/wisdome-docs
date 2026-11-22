#!/usr/bin/env python3
"""Gera o material do curso a partir dos JSON em curso/fonte.

Uso:
  python3 curso/fonte/build.py          gera Markdown + JSON do app + manifesto de áudio
  python3 curso/fonte/gerar_audio.py    gera os arquivos de áudio (macOS, voz do sistema)

Entrada:
  fonte/mapa_curricular.json      estrutura de todos os níveis
  fonte/<nível>/<módulo>.json     conteúdo completo de cada módulo

Saída:
  app/curriculum.json             tudo em um único JSON para importar no app (com caminhos de áudio)
  app/audio_manifest.json         lista de todos os áudios: arquivo, texto e voz
  markdown/<nível>/<módulo>/*.md  uma aula por arquivo + revisão do módulo
  markdown/MAPA_CURRICULAR.md     visão geral de todos os níveis
"""
import copy
import json
import re
import sys
from pathlib import Path

FONTE = Path(__file__).resolve().parent
RAIZ = FONTE.parent
MD = RAIZ / "markdown"
APP = RAIZ / "app"
AUDIO_PREFIX = "audio"

EX_TYPES = {"multiple_choice", "fill_blank", "translate", "order_words", "match",
            "true_false", "answer", "dictation", "correct_error"}

# Vozes do macOS (`say -v`). Femininas e masculinas, em inglês americano/britânico.
FEMALE_VOICES = ["Samantha", "Shelley"]
MALE_VOICES = ["Reed", "Daniel"]
NARRATOR = "Samantha"
FEMALE_SPEAKERS = {
    "Ana", "Bel", "Bia", "Bruna", "Camila", "Carol", "Chloe", "Duda", "Ellen", "Emma", "Fernanda",
    "Hana", "Isa", "Jade", "Jess", "Ju", "Laura", "Letícia", "Lia", "Lin", "Luana", "Luiza", "Malu",
    "Mia", "Nanda", "Nina", "Paula", "Rafaela", "Rita", "Rosa", "Tati", "Woman", "Yuki", "App", "GPS",
    "Announcer", "Teacher", "Mom", "Ms. Park", "Dr. Silva", "Assistant", "Expert", "Doctor",
    "Carolina", "Dona Célia", "Juliana", "Jéssica", "Kate", "Consultant", "Journalist", "Guide", "Mentor",
    "Athlete", "Counselor", "Grandma", "HR Manager", "Recruiter", "Reviewer", "Scientist", "Speaker",
    "Voice 1", "Voice 3", "Márcia", "Priya",
}
MALE_SPEAKERS = {
    "André", "Ben", "Bruno", "Caio", "Diego", "Dr. Lee", "Father", "Gui", "Guest", "Igor", "Jack",
    "Kai", "Leo", "Lucas", "Man", "Mark", "Mateus", "Mr. Cole", "Paulo", "Pedro", "Rafa", "Rafael",
    "Rodrigo", "Theo", "Tiago", "Tom", "Vini", "Driver", "Dad", "Grandpa", "Teen", "Tourist", "Chef",
    "Waiter", "Director", "Dr. Lima", "Seu Antônio", "Uncle", "Coach", "Captain", "Educator", "Voice 2", "Daniel",
}


def slug(s):
    s = re.sub(r"[^\w\s-]", "", s.lower())
    return re.sub(r"[\s_]+", "-", s).strip("-")


def table(headers, rows):
    out = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def details(summary, body):
    return f"<details>\n<summary>{summary}</summary>\n\n{body}\n\n</details>\n"


# ---------------------------------------------------------------- áudio

class Audio:
    """Atribui um arquivo de áudio a cada trecho falado e monta o manifesto."""

    def __init__(self):
        self.manifest = []

    def add(self, lesson_id, level, name, text, voice=NARRATOR, parts=None):
        path = f"{AUDIO_PREFIX}/{level}/{lesson_id}/{name}.m4a"
        entry = {"file": path, "text": text, "voice": voice}
        if parts:
            entry["parts"] = parts  # faixa composta: concatenação de outras faixas
        self.manifest.append(entry)
        return path

    @staticmethod
    def cast(lines):
        """Escolhe uma voz para cada personagem de um diálogo."""
        voices, used_f, used_m = {}, 0, 0
        for ln in lines:
            sp = ln["speaker"]
            if sp in voices:
                continue
            if sp in FEMALE_SPEAKERS:
                female = True
            elif sp in MALE_SPEAKERS:
                female = False
            else:  # papéis genéricos (Host, Staff...): contrasta com quem já fala
                female = used_f <= used_m
            if female:
                voices[sp] = FEMALE_VOICES[used_f % len(FEMALE_VOICES)]
                used_f += 1
            else:
                voices[sp] = MALE_VOICES[used_m % len(MALE_VOICES)]
                used_m += 1
        return voices

    def track(self, lesson_id, level, prefix, lines):
        voices = self.cast(lines)
        parts = []
        for i, ln in enumerate(lines, 1):
            ln["audio"] = self.add(lesson_id, level, f"{prefix}-{i:02d}", ln["en"], voices[ln["speaker"]])
            parts.append(ln["audio"])
        full = " ".join(ln["en"] for ln in lines)
        return self.add(lesson_id, level, f"{prefix}-full", full, parts=parts)


def attach_audio(audio, level, les):
    lid = les["id"]
    for i, v in enumerate(les["vocabulary"], 1):
        v["audio"] = audio.add(lid, level, f"vocab-{i:02d}", v["en"])
    for i, c in enumerate(les.get("chunks", []), 1):
        c["audio"] = audio.add(lid, level, f"chunk-{i:02d}", c["en"])
    for i, e in enumerate(les["grammar"].get("examples", []), 1):
        e["audio"] = audio.add(lid, level, f"example-{i:02d}", e["en"])
    for i, p in enumerate(les["pronunciation"].get("practice", []), 1):
        les["pronunciation"].setdefault("practice_audio", []).append(
            audio.add(lid, level, f"pron-{i:02d}", re.sub(r"\(.*?\)|→.*|=.*|\"", "", p).strip()))
    les["dialogue"]["audio"] = audio.track(lid, level, "dialogue", les["dialogue"]["lines"])
    if les.get("listening"):
        les["listening"]["audio"] = audio.track(lid, level, "listening", les["listening"]["lines"])
    les["reading"]["audio"] = audio.add(lid, level, "reading", les["reading"]["text"].replace("\n", ". "))
    attach_exercise_audio(audio, level, lid, les["exercises"])


def attach_exercise_audio(audio, level, lid, exs):
    for ex in exs:
        if ex["type"] != "dictation":
            continue
        for i, it in enumerate(ex["items"], 1):
            spoken = re.sub(r"\s*\(.*?\)", "", it["answer"].split(" / ")[0])
            if re.fullmatch(r"([A-Z]-)+[A-Z]", spoken):  # soletrar: J-E-S-S
                spoken = ", ".join(spoken.split("-"))
            spoken = spoken.replace("@", " at ").replace(".com", " dot com").replace("_", " underscore ")
            it["audio"] = audio.add(lid, level, f"{ex['id']}-{i:02d}", spoken)


# ---------------------------------------------------------------- validação

def validate_exercises(exs, where):
    errors = []
    ids = [e.get("id") for e in exs]
    if len(ids) != len(set(ids)):
        errors.append(f"{where}: ids de exercício repetidos {ids}")
    for ex in exs:
        if ex.get("type") not in EX_TYPES:
            errors.append(f"{where}/{ex.get('id')}: tipo inválido {ex.get('type')}")
        if not ex.get("instruction"):
            errors.append(f"{where}/{ex.get('id')}: falta instruction (inglês)")
        for i, it in enumerate(ex.get("items", [])):
            if "answer" not in it:
                errors.append(f"{where}/{ex.get('id')} item {i+1}: sem resposta")
            if ex.get("type") == "multiple_choice" and it.get("answer") not in it.get("options", []):
                errors.append(f"{where}/{ex.get('id')} item {i+1}: resposta fora das opções")
            if ex.get("type") == "true_false" and it.get("answer") not in (True, False):
                errors.append(f"{where}/{ex.get('id')} item {i+1}: resposta deve ser true/false")
    return errors


def validate_lesson(les):
    errors = validate_exercises(les["exercises"], les["id"])
    for key in ("listening", "dialogue", "reading", "speaking", "writing"):
        if not les.get(key):
            errors.append(f"{les['id']}: falta a seção {key}")
    if les.get("speaking") and not les["speaking"].get("instruction"):
        errors.append(f"{les['id']}: speaking sem instruction (inglês)")
    if les.get("writing") and not les["writing"].get("task"):
        errors.append(f"{les['id']}: writing sem task (inglês)")
    return errors


# ---------------------------------------------------------------- Markdown

def a(path, depth=3):
    """Link relativo do arquivo .md (markdown/<nível>/<módulo>/) até o áudio."""
    return f"[🔊]({'../' * depth}{path})" if path else ""


def render_exercises(exs, key_lines):
    out = []
    for n, ex in enumerate(exs, 1):
        out.append(f"### Exercise {n} — {ex['title']}\n\n_{ex['instruction']}_\n")
        key = []
        for i, it in enumerate(ex["items"], 1):
            if ex["type"] == "dictation":
                line = f"{i}. {a(it.get('audio'))} ________________________________"
            elif ex["type"] == "correct_error":
                line = f"{i}. ❌ {it['prompt']} → ____________________"
            else:
                line = f"{i}. {it['prompt']}"
            if ex["type"] == "multiple_choice":
                line += "  \n   " + " · ".join(f"( ) {o}" for o in it["options"])
            elif ex["type"] == "true_false":
                line += "  \n   ( ) True ( ) False"
            out.append(line)
            ans = it["answer"]
            if isinstance(ans, bool):
                ans = "True" if ans else "False"
            key.append(f"{i}. {ans}")
        out.append("")
        key_lines.append(f"**Exercise {n}:** " + " · ".join(key))
    return out


def render_lesson(mod, les):
    o = [f"# {les['title']}", f"**{les['id']} · {mod['title']}** — {les['subtitle_pt']}  ",
         f"⏱ {les.get('duration_min', 50)} min\n"]
    o.append("## 🎯 Nesta aula você vai\n" + "\n".join(f"- {x}" for x in les["objectives"]) + "\n")

    w = les["warmup"]
    o.append("## 🔥 Warm-up\n" + w["text_pt"] + "\n")
    o += [f"- {q}" for q in w.get("questions", [])]
    o.append("")

    o.append("## 📚 Vocabulary\n")
    o.append(table(["", "English", "Português", "Pronúncia aproximada"],
                   [[a(v.get("audio")), v["en"], v["pt"], v.get("say", "")] for v in les["vocabulary"]]) + "\n")
    if les.get("chunks"):
        o.append("### Chunks\n_Aprenda estas frases inteiras, não palavra por palavra._\n")
        o.append(table(["", "English", "Português"], [[a(c.get("audio")), c["en"], c["pt"]] for c in les["chunks"]]) + "\n")

    g = les["grammar"]
    o.append(f"## 🧩 Grammar: {g['title']}\n\n{g['explanation_pt']}\n")
    if g.get("table"):
        o.append(table(g["table"]["headers"], g["table"]["rows"]) + "\n")
    if g.get("examples"):
        o.append("**Examples:**\n" + "\n".join(f"- {a(e.get('audio'))} {e['en']} — _{e['pt']}_" for e in g["examples"]) + "\n")
    if g.get("tip_pt"):
        o.append(f"> 💡 **Dica:** {g['tip_pt']}\n")

    o.append("## ⚠️ Atenção, brasileiro!\n")
    for m in les["common_mistakes"]:
        o.append(f"- ❌ {m['wrong']}  \n  ✅ **{m['right']}**  \n  {m['why_pt']}")
    o.append("")

    p = les["pronunciation"]
    o.append(f"## 🗣️ Pronunciation: {p['focus']}\n\n{p['tip_pt']}\n")
    pa = p.get("practice_audio", [])
    o += [f"- {a(pa[i] if i < len(pa) else None)} {x}" for i, x in enumerate(p.get("practice", []))]
    o.append("")

    d = les["dialogue"]
    o.append(f"## 💬 Dialogue — {d['title']}\n\n_{d['context_pt']}_\n\n🎧 Ouça o diálogo completo: {a(d.get('audio'))}\n")
    o.append(table(["", "", "English"], [[a(l.get("audio")), f"**{l['speaker']}**", l["en"]] for l in d["lines"]]) + "\n")
    o.append(details("Ver tradução", table(["", "Português"], [[f"**{l['speaker']}**", l["pt"]] for l in d["lines"]])))

    key = []
    li = les.get("listening")
    if li:
        o.append(f"## 🎧 Listening — {li['title']}\n\n_{li['context_pt']}_\n\n"
                 f"**Listen first, without reading.** {a(li.get('audio'))}\n\n**Questions:**")
        o += [f"{i}. {q['q']}" for i, q in enumerate(li["questions"], 1)]
        o.append("")
        o.append(details("Transcript", "\n\n".join(f"**{l['speaker']}:** {l['en']}" for l in li["lines"])))
        key.append("**Listening:** " + " · ".join(f"{i}. {q['answer']}" for i, q in enumerate(li["questions"], 1)))

    v = les.get("video")
    if v:
        o.append(f"## 🎬 TED Talk — {v['title']}\n\n**{v['speaker']}** · [Assistir no TED]({v['url']})"
                 + (f" · [Playlist da escola]({v['playlist']})" if v.get("playlist") else "") + "\n")
        o.append(v["task_pt"] + "\n")
        o += [f"{i}. {q}" for i, q in enumerate(v["questions"], 1)]
        o.append("")

    r = les["reading"]
    text = r["text"].replace("\n", "  \n")
    o.append(f"## 📖 Reading — {r['title']} {a(r.get('audio'))}\n\n{text}\n\n**Questions:**")
    o += [f"{i}. {q['q']}" for i, q in enumerate(r["questions"], 1)]
    o.append("")
    key.append("**Reading:** " + " · ".join(f"{i}. {q['answer']}" for i, q in enumerate(r["questions"], 1)))

    o.append("## ✏️ Exercises\n")
    o += render_exercises(les["exercises"], key)

    s = les["speaking"]
    o.append("## 🎤 Speaking\n\n" + s["instruction"] + "\n")
    o += [f"{i}. {q}" for i, q in enumerate(s["questions"], 1)]
    o.append("")
    o.append(details("Instrução em português", s["instruction_pt"]))

    wr = les["writing"]
    o.append(f"## 📝 Writing\n\n{wr['task']}\n\n**Model:**\n\n> " + wr["model"].replace("\n", "  \n> ") + "\n")
    o.append(details("Instrução em português", wr["task_pt"]))

    if les.get("culture_note"):
        c = les["culture_note"]
        o.append(f"## 🌎 Cultura & Curiosidade — {c['title']}\n\n{c['text_pt']}\n")

    o.append("## ✅ Resumo\n" + "\n".join(f"- {x}" for x in les["summary_pt"]) + "\n")
    o.append("---\n## 🔑 Answer key\n\n" + "\n\n".join(key) + "\n")
    return "\n".join(o)


def render_review(mod):
    rv = mod["review"]
    o = [f"# Review — {mod['title']}", f"**{mod['id']}** — {rv['intro_pt']}\n",
         "## O que você aprendeu neste módulo\n" + "\n".join(f"- {x}" for x in mod["can_do"]) + "\n",
         "## ✏️ Review exercises\n"]
    key = []
    o += render_exercises(rv["exercises"], key)
    o.append("## 🎤 Free conversation\n\n" + rv["speaking_pt"] + "\n")
    o += [f"{i}. {q}" for i, q in enumerate(rv["speaking_questions"], 1)]
    o.append("\n## 🚀 Mini-projeto\n\n" + rv["project_pt"] + "\n")
    o.append("## Autoavaliação\nMarque o que você já consegue fazer:\n" + "\n".join(f"- [ ] {x}" for x in mod["can_do"]) + "\n")
    o.append("---\n## 🔑 Answer key\n\n" + "\n\n".join(key) + "\n")
    return "\n".join(o)


def render_map(mapa):
    o = [f"# {mapa['course']} — Mapa Curricular\n", mapa["methodology_pt"] + "\n",
         "## Estrutura de cada aula\n" + "\n".join(f"{i}. {x}" for i, x in enumerate(mapa["lesson_structure"], 1)) + "\n"]
    for lv in mapa["levels"]:
        o.append(f"---\n## {lv['name']}  \n_Status: {lv['status']} · ~{lv['hours_estimated']} h_\n\n{lv['description_pt']}\n")
        if lv.get("sequence_note_pt"):
            o.append(f"> {lv['sequence_note_pt']}\n")
        o.append("**Material de referência usado como guia:** " + ", ".join(lv["sources"]) + "\n")
        for m in lv["modules"]:
            o.append(f"### {m['id']} · {m['title']}\n_{m['theme_pt']}_\n")
            o.append("**Ao final o aluno consegue:** " + "; ".join(m["can_do"]) + ".\n")
            o.append(table(["Aula", "Título", "Gramática", "Vocabulário"],
                           [[l["id"], l["title"], l["grammar"], l["vocab"]] for l in m["lessons"]]) + "\n")
    return "\n".join(o)


# ---------------------------------------------------------------- main

def main():
    mapa = json.loads((FONTE / "mapa_curricular.json").read_text())
    errors = []
    audio = Audio()
    app = {k: mapa[k] for k in ("course", "version", "language_of_instruction", "methodology_pt", "lesson_structure")}
    app["audio_base_path"] = "audio/"
    app["levels"] = []
    MD.mkdir(exist_ok=True)
    (MD / "MAPA_CURRICULAR.md").write_text(render_map(mapa))
    count = 0
    for lv in mapa["levels"]:
        lv_out = {k: v for k, v in lv.items() if k != "modules"}
        lv_out["modules"] = []
        for m in lv["modules"]:
            f = FONTE / lv.get("folder", lv["id"]) / f"{m['id']}.json"
            if not f.exists():
                lv_out["modules"].append({**m, "content_status": "planned"})
                continue
            full = copy.deepcopy(json.loads(f.read_text()))
            mapped = [l["id"] for l in m["lessons"]]
            written = [l["id"] for l in full["lessons"]]
            if mapped != written:
                errors.append(f"{m['id']}: aulas no mapa {mapped} != escritas {written}")
            for les in full["lessons"]:
                errors += validate_lesson(les)
                attach_audio(audio, lv.get("folder", lv["id"]), les)
            errors += validate_exercises(full["review"]["exercises"], m["id"] + "-review")
            attach_exercise_audio(audio, lv.get("folder", lv["id"]), m["id"] + "-review", full["review"]["exercises"])
            folder = MD / lv.get("folder", lv["id"]) / f"{m['id']}-{slug(m['title'])}"
            if folder.parent.exists():
                for old in folder.parent.glob(f"{m['id']}-*"):
                    if old != folder:
                        for x in old.glob("*.md"):
                            x.unlink()
                        old.rmdir()
            folder.mkdir(parents=True, exist_ok=True)
            for i, les in enumerate(full["lessons"], 1):
                (folder / f"{i:02d}-{slug(les['title'])}.md").write_text(render_lesson(full, les))
                count += 1
            (folder / "05-review.md").write_text(render_review(full))
            lv_out["modules"].append({**full, "content_status": "complete"})
        app["levels"].append(lv_out)
    APP.mkdir(exist_ok=True)
    (APP / "curriculum.json").write_text(json.dumps(app, ensure_ascii=False, indent=2))
    (APP / "audio_manifest.json").write_text(json.dumps(audio.manifest, ensure_ascii=False, indent=2))
    if errors:
        print("ERROS:\n" + "\n".join(errors))
        sys.exit(1)
    print(f"OK: {count} aulas geradas, {len(audio.manifest)} áudios no manifesto.")


if __name__ == "__main__":
    main()
