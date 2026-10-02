#!/usr/bin/env python3
"""Analiza un archivo con NotebookLM usando ese archivo como contexto.

Uso:
    python3 scripts/nlm_analizar.py <archivo> "<pregunta>"

Funcionamiento:
  1. Usa un cuaderno de NotebookLM por repositorio (lo crea la primera vez).
  2. Sube el archivo como fuente. Si ya se subió y no ha cambiado (mismo hash),
     reutiliza la fuente; si cambió, borra la fuente antigua y sube la nueva.
  3. Pregunta a NotebookLM limitando la respuesta a esa fuente (-s <source_id>),
     de modo que el análisis se basa solo en el archivo indicado.

El mapeo archivo -> fuente se guarda en .notebooklm/cache.json (ignorado por git).
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_PATH = REPO_ROOT / ".notebooklm" / "cache.json"
NOTEBOOK_TITLE = f"Análisis: {REPO_ROOT.name}"


def run(*args: str) -> dict:
    proc = subprocess.run(["notebooklm", *args, "--json"], capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"Error en `notebooklm {' '.join(args)}`:\n{proc.stderr or proc.stdout}")
    return json.loads(proc.stdout) if proc.stdout.strip() else {}


def load_cache() -> dict:
    try:
        return json.loads(CACHE_PATH.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {"notebook_id": None, "files": {}}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False))


def notebook_id(cache: dict) -> str:
    nb = os.environ.get("NOTEBOOKLM_NOTEBOOK") or cache.get("notebook_id")
    if nb:
        return nb
    nb = run("create", NOTEBOOK_TITLE)["notebook"]["id"]
    cache["notebook_id"] = nb
    save_cache(cache)
    return nb


def source_for(path: Path, nb: str, cache: dict) -> str:
    key = str(path.relative_to(REPO_ROOT)) if path.is_relative_to(REPO_ROOT) else str(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    entry = cache["files"].get(key)
    if entry and entry["sha256"] == digest:
        return entry["source_id"]
    if entry:
        # El archivo cambió: sustituir la fuente antigua por la versión actual.
        subprocess.run(
            ["notebooklm", "source", "delete", entry["source_id"], "-n", nb, "-y"],
            capture_output=True,
        )
    src = run("source", "add", str(path), "--type", "file", "--title", key, "-n", nb)
    source_id = src["source"]["id"]
    wait = subprocess.run(
        ["notebooklm", "source", "wait", source_id, "-n", nb, "--timeout", "600"],
        capture_output=True,
        text=True,
    )
    if wait.returncode != 0:
        sys.exit(f"La fuente {source_id} no quedó lista:\n{wait.stderr or wait.stdout}")
    cache["files"][key] = {"source_id": source_id, "sha256": digest}
    save_cache(cache)
    return source_id


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    path = Path(sys.argv[1]).resolve()
    question = " ".join(sys.argv[2:])
    if not path.is_file():
        sys.exit(f"No existe el archivo: {path}")

    cache = load_cache()
    nb = notebook_id(cache)
    source_id = source_for(path, nb, cache)
    result = run("ask", question, "-n", nb, "-s", source_id)
    print(result.get("answer", json.dumps(result, indent=2, ensure_ascii=False)))


if __name__ == "__main__":
    main()
