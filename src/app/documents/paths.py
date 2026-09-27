'''Shared filesystem locations for the document pipeline.

These paths are anchored to this module's own directory rather than the
current working directory, so the pipeline behaves identically no matter
where Python is invoked from (``src/``, the repository root, or elsewhere).
'''

import os
from pathlib import Path

# .../src/app/documents — every corpus path hangs off this.
DOCUMENTS_DIR: Path = Path(__file__).resolve().parent

# Directory the 39 public source PDFs are downloaded into, using the exact
# ``filename`` recorded in the sources CSV. Read by PDFLoader and PDFDownloader.
APP_DOCS_DIR: Path = DOCUMENTS_DIR / 'files' / 'comply_sources'

def vector_store_dir(environ=os.environ) -> Path:
    '''VECTOR_STORE_DIR from the environment, or the directory beside this one.

    On Fly the index lives on the machine's volume, and fly.toml points
    VECTOR_STORE_DIR there. A relative value is refused: it would resolve
    against the working directory, which this module exists to rule out, and
    the pipeline deletes whatever this path names when it clears the index.
    '''
    configured = environ.get('VECTOR_STORE_DIR')
    if not configured:
        return DOCUMENTS_DIR / 'vector_store'
    if not Path(configured).is_absolute():
        raise ValueError(f'VECTOR_STORE_DIR must be an absolute path, not {configured!r}.')
    return Path(configured)


# Persistent Chroma storage written by the ingestion step.
VECTOR_STORE_DIR: Path = vector_store_dir()

# The Chroma subdirectory passed to chromadb.PersistentClient.
CHROMA_DIR: Path = VECTOR_STORE_DIR / 'chroma'
