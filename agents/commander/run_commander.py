#!/usr/bin/env python3
"""
Commander — Main REPL / CLI entry point.

Text mode (default):
  python backend/agents/commander/run_commander.py

Voice mode (opens browser with Web Speech API):
  python backend/agents/commander/run_commander.py --voice

Type 'help' or '?' inside the REPL for a list of commands.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Make sibling modules importable when running as a script
_COMMANDER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_COMMANDER_DIR))

import command_parser
import dispatcher


def _process(text: str) -> bool:
    """
    Parse and dispatch one command.
    Returns False if the REPL should exit, True otherwise.
    """
    text = text.strip()
    if not text:
        return True

    intent = command_parser.parse(text)
    result = dispatcher.dispatch(intent)

    if result == "__quit__":
        print("[commander] Até mais! 👋")
        return False

    print(result)
    return True


def _run_text_repl() -> None:
    print("[commander] Pronto. Digite um comando ou 'help' para ver as opções.")
    print("[commander] Ctrl+C ou 'quit' para sair.\n")
    try:
        while True:
            try:
                text = input("commander> ").strip()
            except EOFError:
                break
            if not _process(text):
                break
    except KeyboardInterrupt:
        print("\n[commander] Interrompido.")


def _run_voice_repl() -> None:
    from voice_server import VoiceServer

    server = VoiceServer()
    server.start(open_browser=True)
    print(f"[commander] Voice server up at {server.url}")
    print("[commander] Fale no browser para enviar comandos. Ctrl+C para sair.\n")

    try:
        while True:
            transcript = server.get_transcript(timeout=0.5)
            if transcript is None:
                continue
            print(f"\n[voice] {transcript}")
            if not _process(transcript):
                break
    except KeyboardInterrupt:
        print("\n[commander] Encerrando voice server...")
    finally:
        server.stop()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Commander — Tabzer AI agent dispatcher (text + voice)"
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable voice input via browser Web Speech API (requires Chrome/Edge)",
    )
    args = parser.parse_args()

    if args.voice:
        _run_voice_repl()
    else:
        _run_text_repl()


if __name__ == "__main__":
    main()
