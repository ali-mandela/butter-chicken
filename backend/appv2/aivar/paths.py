"""Where the pipeline writes its output.

Output directories are configured as relative paths ("artifacts",
"tests/generated"), which Python resolves against the CURRENT WORKING
DIRECTORY. That means the same run scatters its files to a different place
depending on where the process happened to be started -- launching Streamlit
from `frontend/` put reports in `frontend/artifacts/` while the CLI put them in
`appv2/artifacts/`, and neither the user nor the report itself said which.

Anchoring relative paths to the project root instead makes output location a
property of the project, not of the shell.
"""

from __future__ import annotations

from pathlib import Path


def project_root() -> Path:
    """The `appv2` directory: the parent of the `aivar` package."""
    return Path(__file__).resolve().parent.parent


def resolve_out_dir(path: str | Path) -> Path:
    """Resolve an output directory against the project root.

    An absolute path is honoured as given, so a caller can still write
    anywhere deliberately. A relative one is anchored to the project root
    rather than the working directory.
    """
    p = Path(path)
    return p if p.is_absolute() else (project_root() / p)
