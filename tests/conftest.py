"""Session-wide test setup.

Imports onnxruntime before any test module gets a chance to import
win11toast (jarvis/interfaces/notify.py, Phase 8). win11toast's winrt
bindings corrupt onnxruntime's native DLL loading for the rest of the
process if win11toast is imported first — confirmed directly (a bare
`import win11toast; import onnxruntime` reproduces it; the reverse order
doesn't). Production code never hits this ordering risk (notify.py imports
win11toast lazily, after any chromadb usage in the same run already
happened), but pytest loads every test module into one shared process
regardless of which phase's tests they belong to, so this import has to be
forced here rather than left to file-collection order.
"""

import onnxruntime  # noqa: F401
