"""Developer Intelligence Platform — UI-agnostic backend package.

Nothing under ``dip`` may import Streamlit (or any UI framework). The UI layer
(``ui/``) depends on these services; the dependency never points the other way.
"""

__version__ = "0.1.0"
