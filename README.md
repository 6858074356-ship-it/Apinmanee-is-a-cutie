# Local AI: Chat with Gemma

A small local web app that sends chat requests from Flask to the Ollama API on this computer. It includes a document collection page for uploading and removing local files, plus local text extraction and retrieval so chat can answer from relevant document passages and link to the source file.

## Requirements

- Python 3.9 or newer
- Ollama installed and running locally
- The `gemma3:1b` model pulled in Ollama

## Setup and run

From this project directory:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
ollama pull gemma3:1b
python app.py
```

On Windows, activate the environment with `.venv\Scripts\activate` instead. Open <http://127.0.0.1:5000/> in your browser. Keep Ollama running while chatting. The server binds to `127.0.0.1` only.

The app uses Ollama's non-streaming `/api/chat` endpoint. Conversation history stays in the current browser tab and is sent with each request. Uploaded PDF, TXT, MD, and DOCX files are stored in `instance/documents/`. The app extracts text, retrieves relevant passages for each question, and returns clickable source links. PDFs should contain selectable text; scanned image-only PDFs need OCR before they can be searched.

Optional settings can be supplied as environment variables:

- `OLLAMA_MODEL` (default `gemma3:1b`)
- `OLLAMA_CHAT_URL` (default `http://127.0.0.1:11434/api/chat`)
- `LOCAL_AI_UPLOAD_DIR` (default `instance/documents` in this project)
- `FLASK_SECRET_KEY` (set a private value if using flash messages beyond a local demo)

If the chat says Ollama is unavailable, start Ollama and confirm the model is installed with `ollama list`. If it says the model is missing, run `ollama pull gemma3:1b`.
