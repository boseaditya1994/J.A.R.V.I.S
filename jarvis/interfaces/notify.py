"""Windows toast delivery for proactive notifications (Phase 8).

Thin wrapper over win11toast, always called through a `notify_fn`
parameter at the caller (see jarvis/interfaces/proactive.py) so tests
substitute a fake instead of popping real toasts — same precedent as
jarvis/voice/tts.py's playback, which also isn't unit-tested directly.

win11toast's winrt bindings are imported lazily, inside notify() rather
than at module load time: importing win11toast before chromadb/onnxruntime
have loaded in the same process corrupts onnxruntime's native DLL loading
for the rest of that process (confirmed directly — reproduces with a bare
`import win11toast; import onnxruntime`, but not in the reverse order).
Deferring the import here means run_morning_brief's own knowledge_search
tool call (if any) always gets to import chromadb/onnxruntime first, since
that happens inside the tool loop, before notify() is ever called at the
end of that same function.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def notify(title: str, message: str) -> bool:
    """Returns True if the toast call completed, False on failure — callers
    (jarvis/interfaces/proactive.py) use this to decide whether to mark a
    reminder notified, so a failure gets retried rather than silently
    dropped."""
    if not message.strip():
        return True

    from win11toast import toast

    try:
        toast(title, message)
        return True
    except Exception:
        logger.exception("win11toast.toast failed")
        return False
