"""Local chat UI for Ollama with a small document collection manager."""

from pathlib import Path
import os
import math
import re
from collections import Counter

import requests
from flask import Flask, jsonify, render_template, request, redirect, url_for, flash, send_from_directory
from werkzeug.utils import secure_filename

from docx import Document
from pypdf import PdfReader


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.environ.get("LOCAL_AI_UPLOAD_DIR", BASE_DIR / "instance" / "documents"))
ALLOWED_EXTENSIONS = {"pdf", "txt", "md", "docx"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
OLLAMA_CHAT_URL = os.environ.get("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:1b")
CHUNK_SIZE = 1100
CHUNK_OVERLAP = 160
MAX_RETRIEVED_CHUNKS = 5
_document_cache = {}

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "local-demo-change-me")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def split_chunks(text, source, page=None):
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + CHUNK_SIZE // 2, end)
            if boundary > start:
                end = boundary
        chunks.append({"text": text[start:end], "source": source, "page": page})
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return chunks


def extract_document(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        reader = PdfReader(str(path))
        chunks = []
        for page_number, page in enumerate(reader.pages, start=1):
            chunks.extend(split_chunks(page.extract_text() or "", path.name, page_number))
        return chunks
    if suffix == ".docx":
        document = Document(str(path))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        return split_chunks(text, path.name)
    if suffix in {".txt", ".md"}:
        return split_chunks(path.read_text(encoding="utf-8", errors="replace"), path.name)
    return []


def indexed_documents():
    chunks = []
    present = set()
    for path in UPLOAD_DIR.iterdir():
        if not path.is_file() or not allowed_file(path.name):
            continue
        key = str(path.resolve())
        present.add(key)
        stat = path.stat()
        cached = _document_cache.get(key)
        signature = (stat.st_mtime_ns, stat.st_size)
        if cached is None or cached[0] != signature:
            try:
                _document_cache[key] = (signature, extract_document(path), None)
            except Exception as exc:
                _document_cache[key] = (signature, [], str(exc))
        chunks.extend(_document_cache[key][1])
    for key in list(_document_cache):
        if key not in present:
            del _document_cache[key]
    return chunks


def retrieve_passages(query, chunks):
    terms = re.findall(r"[\w'-]+", query.casefold())
    query_terms = set(terms)
    if not query_terms or not chunks:
        return []
    tokenized = [re.findall(r"[\w'-]+", item["text"].casefold()) for item in chunks]
    document_frequency = Counter(term for term in query_terms for tokens in tokenized if term in set(tokens))
    scored = []
    total = len(chunks)
    for item, tokens in zip(chunks, tokenized):
        counts = Counter(tokens)
        length_norm = 0.25 + 0.75 * (len(tokens) / max(1, sum(map(len, tokenized)) / total))
        score = sum(
            math.log(1 + (total - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
            * (counts[term] * 2.2 / (counts[term] + 1.2 * length_norm))
            for term in query_terms
        )
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [item for _score, item in scored[:MAX_RETRIEVED_CHUNKS]]


@app.get("/")
def index():
    return render_template("index.html", model=OLLAMA_MODEL)


@app.get("/documents")
def documents():
    files = sorted(
        ({"name": p.name, "size": p.stat().st_size} for p in UPLOAD_DIR.iterdir() if p.is_file()),
        key=lambda item: item["name"].casefold(),
    )
    return render_template("documents.html", files=files, max_mb=MAX_UPLOAD_BYTES // (1024 * 1024))


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    messages = payload.get("messages")
    if not isinstance(messages, list) or not messages:
        return jsonify(error="Please enter a message and try again."), 400

    clean_messages = []
    for message in messages[-40:]:
        if not isinstance(message, dict):
            return jsonify(error="The conversation format was invalid. Please refresh and try again."), 400
        role, content = message.get("role"), message.get("content")
        if role not in {"user", "assistant"} or not isinstance(content, str):
            return jsonify(error="The conversation format was invalid. Please refresh and try again."), 400
        if content.strip():
            clean_messages.append({"role": role, "content": content[:20000]})
    if not clean_messages or clean_messages[-1]["role"] != "user":
        return jsonify(error="Please submit a new question."), 400

    passages = retrieve_passages(clean_messages[-1]["content"], indexed_documents())
    sources = []
    if passages:
        context_lines = []
        for passage in passages:
            location = f", page {passage['page']}" if passage["page"] else ""
            citation = f"{passage['source']}{location}"
            context_lines.append(f"[Source: {citation}]\n{passage['text']}")
            source = {"name": passage["source"], "page": passage["page"],
                      "url": url_for("open_document", filename=passage["source"]) +
                            (f"#page={passage['page']}" if passage["page"] and passage["source"].lower().endswith(".pdf") else "")}
            if source not in sources:
                sources.append(source)
        clean_messages[-1]["content"] += (
            "\n\nUse the following excerpts from the user's uploaded documents when relevant. "
            "Answer from the excerpts where possible. Cite each used excerpt with its exact filename "
            "and page number when present, using [Source: filename, page N]. If the excerpts do not "
            "contain the answer, say so clearly.\n\n" + "\n\n".join(context_lines)
        )

    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json={"model": OLLAMA_MODEL, "messages": clean_messages, "stream": False},
            timeout=(3.05, 300),
        )
        response.raise_for_status()
        result = response.json()
        answer = result.get("message", {}).get("content")
        if not isinstance(answer, str) or not answer.strip():
            return jsonify(error="Ollama returned an empty response. Please try again."), 502
        return jsonify(reply=answer, sources=sources)
    except requests.exceptions.ConnectionError:
        return jsonify(error="Ollama is unavailable. Start Ollama and make sure gemma3:1b is installed, then try again."), 503
    except requests.exceptions.Timeout:
        return jsonify(error="Ollama took too long to respond. Please try again."), 504
    except requests.exceptions.HTTPError as exc:
        details = ""
        try:
            details = exc.response.json().get("error", "")
        except (ValueError, AttributeError):
            pass
        if exc.response is not None and exc.response.status_code == 404:
            message = f"Ollama could not find model {OLLAMA_MODEL}. Run `ollama pull {OLLAMA_MODEL}` and try again."
        else:
            message = "Ollama returned an error. " + (details[:300] if details else "Please try again.")
        return jsonify(error=message), 502
    except (ValueError, requests.exceptions.RequestException):
        return jsonify(error="The response from Ollama was invalid. Please try again."), 502


@app.post("/documents/upload")
def upload_document():
    file = request.files.get("file")
    if file is None or not file.filename:
        flash("Choose a file to upload.", "error")
        return redirect(url_for("documents"))
    safe_name = secure_filename(file.filename)
    if not safe_name or not allowed_file(safe_name):
        flash("Upload a PDF, TXT, MD, or DOCX file.", "error")
        return redirect(url_for("documents"))
    destination = UPLOAD_DIR / safe_name
    if destination.exists():
        flash("A file with that name is already in your collection.", "error")
        return redirect(url_for("documents"))
    file.save(destination)
    _document_cache.pop(str(destination.resolve()), None)
    flash(f"Uploaded {safe_name}.", "success")
    return redirect(url_for("documents"))


@app.post("/documents/delete/<path:filename>")
def delete_document(filename):
    safe_name = secure_filename(filename)
    target = (UPLOAD_DIR / safe_name).resolve()
    if target.parent != UPLOAD_DIR.resolve() or not target.is_file():
        flash("That document could not be found.", "error")
    else:
        target.unlink()
        _document_cache.pop(str(target), None)
        flash(f"Deleted {safe_name}.", "success")
    return redirect(url_for("documents"))


@app.get("/documents/open/<path:filename>")
def open_document(filename):
    safe_name = secure_filename(filename)
    target = (UPLOAD_DIR / safe_name).resolve()
    if target.parent != UPLOAD_DIR.resolve() or not target.is_file():
        return "Document not found", 404
    return send_from_directory(UPLOAD_DIR, safe_name, as_attachment=False)


@app.errorhandler(413)
def file_too_large(_error):
    flash(f"The file is too large. Maximum size is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", "error")
    return redirect(url_for("documents")), 303


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
