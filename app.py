from __future__ import annotations

import os
import re
import uuid
from pathlib import Path

import requests
from flask import Flask, jsonify, render_template, request
from pypdf import PdfReader
from werkzeug.utils import secure_filename


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("CHAT_DATA_DIR", BASE_DIR / "instance" / "documents"))
ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_DOCUMENT_CHARS = 100_000
MAX_TOTAL_CONTEXT_CHARS = 24_000
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:1b")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES


def document_text(path: Path) -> str:
    """Extract readable text from a supported local document."""
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        text = path.read_text(encoding="utf-8", errors="replace")
    return text[:MAX_DOCUMENT_CHARS]


def list_documents() -> list[dict]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    for path in sorted(DATA_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not path.is_file() or path.suffix.lower() not in {".pdf", ".txt", ".md"}:
            continue
        name_file = path.with_suffix(path.suffix + ".name")
        name = name_file.read_text(encoding="utf-8") if name_file.exists() else path.name
        documents.append({"id": path.stem, "name": name, "size": path.stat().st_size})
    return documents


@app.get("/")
def index():
    return render_template("index.html", model=MODEL)


@app.get("/api/documents")
def get_documents():
    return jsonify(list_documents())


@app.post("/api/documents")
def upload_document():
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Choose a PDF, TXT, or Markdown file."), 400
    original_name = secure_filename(uploaded.filename)
    suffix = Path(original_name).suffix.lower()
    if suffix.lstrip(".") not in ALLOWED_EXTENSIONS:
        return jsonify(error="Supported formats are PDF, TXT, and MD."), 400
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    destination = DATA_DIR / f"{uuid.uuid4().hex}{suffix}"
    uploaded.save(destination)
    try:
        document_text(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        return jsonify(error="This document could not be read. Check that it is a valid PDF or UTF-8 text file."), 400
    (destination.with_suffix(destination.suffix + ".name")).write_text(original_name, encoding="utf-8")
    return jsonify(id=destination.stem, name=original_name, size=destination.stat().st_size), 201


@app.delete("/api/documents/<document_id>")
def delete_document(document_id: str):
    if not re.fullmatch(r"[a-f0-9]{32}", document_id):
        return jsonify(error="Document not found."), 404
    matches = list(DATA_DIR.glob(f"{document_id}.*"))
    if not matches:
        return jsonify(error="Document not found."), 404
    for path in matches:
        if path.is_file():
            path.unlink()
    return "", 204


def document_context() -> str:
    chunks = []
    used = 0
    for item in list_documents():
        path = next((p for p in DATA_DIR.glob(f"{item['id']}.*") if p.suffix.lower() in {".pdf", ".txt", ".md"}), None)
        if path is None:
            continue
        try:
            text = document_text(path).strip()
        except Exception:
            continue
        if not text:
            continue
        room = MAX_TOTAL_CONTEXT_CHARS - used
        if room <= 0:
            break
        display_name = item["name"]
        excerpt = text[:room]
        chunks.append(f"--- {display_name} ---\n{excerpt}")
        used += len(excerpt)
    if not chunks:
        return ""
    return "The user has uploaded these local documents. Use them as reference when relevant, and say when they do not contain the answer.\n\n" + "\n\n".join(chunks)


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Send a conversation with at least one message."), 400
    safe_messages = []
    for message in messages[-20:]:
        if not isinstance(message, dict) or message.get("role") not in {"user", "assistant"}:
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            safe_messages.append({"role": message["role"], "content": content[:8000]})
    if not safe_messages or safe_messages[-1]["role"] != "user":
        return jsonify(error="The latest message must be from you."), 400

    context = document_context()
    if context:
        first_user = next((i for i, item in enumerate(safe_messages) if item["role"] == "user"), None)
        safe_messages.insert(first_user, {"role": "user", "content": f"Reference documents (use only if relevant):\n{context}"})
    try:
        response = requests.post(
            f"{OLLAMA_URL.rstrip('/')}/api/chat",
            json={"model": MODEL, "messages": safe_messages, "stream": False},
            timeout=(5, 300),
        )
        response.raise_for_status()
        answer = response.json().get("message", {}).get("content")
        if not isinstance(answer, str):
            raise ValueError("Ollama returned an unexpected response.")
        return jsonify(answer=answer)
    except requests.exceptions.ConnectionError:
        return jsonify(error=f"Cannot reach Ollama at {OLLAMA_URL}. Start Ollama and make sure {MODEL} is available."), 503
    except requests.exceptions.Timeout:
        return jsonify(error="Ollama took too long to respond. Try again or use a smaller model."), 504
    except (requests.RequestException, ValueError) as exc:
        detail = "Ollama returned an error."
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            detail += f" (HTTP {exc.response.status_code})"
        return jsonify(error=detail), 502


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="That file is larger than the 50 MB upload limit."), 413


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
