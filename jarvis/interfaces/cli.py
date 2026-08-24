"""Phase 1-2 entrypoint: type a message, or press Enter to speak one."""

from __future__ import annotations

import sys

from jarvis.core import commands
from jarvis.core.config import load_settings
from jarvis.core.orchestrator import Orchestrator
from jarvis.memory.store import MemoryStore
from jarvis.voice import stt, tts

EXIT_WORDS = {"exit", "quit"}


def main() -> None:
    # Windows consoles don't always default stdout to UTF-8; Claude's
    # replies routinely include em dashes/curly quotes that would otherwise
    # come out as mojibake or crash the print.
    sys.stdout.reconfigure(encoding="utf-8")

    settings = load_settings()
    store = MemoryStore()

    def confirm_tool_call(prompt: str) -> bool:
        answer = input(f"{prompt} Type 'yes' to allow: ").strip().lower()
        return answer == "yes"

    orchestrator = Orchestrator(settings, store, confirm=confirm_tool_call)

    print(f"{settings.jarvis_name} is ready. Type a message, or press Enter to speak.")
    print("Type 'exit' or 'quit' to stop.\n")

    while True:
        user_text = input("> ").strip()

        if user_text.lower() in EXIT_WORDS:
            print(f"{settings.jarvis_name}: Goodbye.")
            break

        if not user_text:
            audio = stt.record_until_enter()
            user_text = stt.transcribe(audio, model_size=settings.stt_model)
            if not user_text:
                print("(didn't catch that — try again)")
                continue
            print(f"you said: {user_text}")

        reply = orchestrator.handle_turn(user_text)

        if reply == commands.FORGET_EVERYTHING:
            confirm = input(
                "This deletes all stored facts, tasks, and history. "
                "Type 'yes' to confirm: "
            ).strip().lower()
            if confirm == "yes":
                store.forget_everything()
                reply = "Done. I've forgotten everything I knew."
            else:
                reply = "Okay — I left your memory as it was."
            store.log_turn(user_text, reply)

        print(f"{settings.jarvis_name}: {reply}")
        tts.speak(reply, voice=settings.tts_voice)


if __name__ == "__main__":
    main()
