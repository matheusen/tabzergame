"""
Commander — Voice Server
Minimal HTTP server (stdlib only) that:
1. Serves an HTML page with the Web Speech API microphone input
2. Receives POST /transcript with {"transcript": "..."} from the page
3. Puts transcripts into a threading.Queue for the REPL to consume

The server is started in a daemon thread; the caller opens the browser.
"""
from __future__ import annotations

import json
import queue
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

_PORT = 7432
_HOST = "127.0.0.1"

# HTML page with Web Speech API — sends transcript as JSON POST to /transcript
_HTML = """\
<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8"/>
<title>Commander — Voice Input</title>
<style>
  body { font-family: sans-serif; background: #0d1117; color: #e6edf3;
         display:flex; flex-direction:column; align-items:center;
         justify-content:center; min-height:100vh; gap:1rem; }
  button { padding: .7rem 2rem; font-size:1.1rem; border-radius:8px;
           border:none; cursor:pointer; }
  #start { background:#238636; color:#fff; }
  #stop  { background:#da3633; color:#fff; display:none; }
  #status { font-size:.9rem; color:#8b949e; min-height:1.5rem; }
  #log { width:90vw; max-width:640px; background:#161b22; padding:1rem;
         border-radius:8px; font-size:.85rem; white-space:pre-wrap;
         min-height:120px; max-height:40vh; overflow-y:auto; }
</style>
</head>
<body>
<h2>🎙 Commander — Voice Input</h2>
<div id="status">Pronto. Clique em Iniciar para falar.</div>
<button id="start" onclick="startListening()">▶ Iniciar</button>
<button id="stop"  onclick="stopListening()">■ Parar</button>
<div id="log">(aguardando transcrições…)</div>
<script>
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
let recognition = null;
let active = false;

function log(msg) {
  const el = document.getElementById('log');
  el.textContent += msg + '\\n';
  el.scrollTop = el.scrollHeight;
}

function setStatus(msg) {
  document.getElementById('status').textContent = msg;
}

function startListening() {
  if (!SpeechRecognition) {
    setStatus('Web Speech API não disponível — use Chrome ou Edge.');
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = 'pt-BR';
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;
  recognition.continuous = false;

  recognition.onstart = () => {
    active = true;
    setStatus('Ouvindo…');
    document.getElementById('start').style.display = 'none';
    document.getElementById('stop').style.display = 'inline-block';
  };

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript.trim();
    log('> ' + transcript);
    setStatus('Processando…');
    sendTranscript(transcript);
  };

  recognition.onerror = (event) => {
    log('[erro] ' + event.error);
    setStatus('Erro: ' + event.error);
    resetUI();
  };

  recognition.onend = () => {
    if (active) {
      // Auto-restart for continuous mode
      try { recognition.start(); } catch(_) { resetUI(); }
    } else {
      resetUI();
    }
  };

  recognition.start();
}

function stopListening() {
  active = false;
  if (recognition) recognition.stop();
  resetUI();
}

function resetUI() {
  document.getElementById('start').style.display = 'inline-block';
  document.getElementById('stop').style.display = 'none';
  setStatus('Pronto.');
}

async function sendTranscript(text) {
  try {
    const resp = await fetch('/transcript', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ transcript: text })
    });
    const data = await resp.json();
    log('← ' + (data.result || 'ok'));
    setStatus('Pronto.');
    // Re-start after a short pause
    setTimeout(startListening, 800);
  } catch(err) {
    log('[fetch error] ' + err);
    setStatus('Erro ao enviar.');
    setTimeout(startListening, 1500);
  }
}
</script>
</body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    """HTTP request handler shared by all voice server instances."""
    transcript_queue: "queue.Queue[str]" = queue.Queue()

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # silence access logs

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            body = _HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/transcript":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                data = json.loads(body)
                transcript = str(data.get("transcript", "")).strip()
                if transcript:
                    _Handler.transcript_queue.put(transcript)
                response = json.dumps({"result": "queued"}).encode("utf-8")
            except Exception:
                response = json.dumps({"result": "error"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)
        else:
            self.send_error(404)


class VoiceServer:
    """Starts the voice HTTP server in a daemon thread and exposes a transcript queue."""

    def __init__(self, host: str = _HOST, port: int = _PORT) -> None:
        self.host = host
        self.port = port
        self.url = f"http://{host}:{port}"
        self.transcript_queue: "queue.Queue[str]" = _Handler.transcript_queue
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self, open_browser: bool = True) -> None:
        self._server = HTTPServer((self.host, self.port), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        print(f"[voice_server] Listening at {self.url}")
        if open_browser:
            webbrowser.open(self.url)

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()

    def get_transcript(self, timeout: float = 0.5) -> str | None:
        try:
            return self.transcript_queue.get(timeout=timeout)
        except queue.Empty:
            return None
