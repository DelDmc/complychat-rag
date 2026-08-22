from dotenv import load_dotenv
from .pdf_loader import PDFLoader
from .document_splitter import DocumentSplitter
from .pdf_downloader import PDFDownloader

import logging
import os
import shutil
import time
from typing import Optional

load_dotenv()

logger = logging.getLogger(__name__)

# Env values that count as "yes". Anything else, including unset, is no.
_TRUTHY = {'1', 'true', 'yes', 'on'}

ALLOW_PARTIAL_CORPUS_ENV = 'ALLOW_PARTIAL_CORPUS'

def allow_partial_from_env() -> bool:
    '''Whether a reduced corpus has been consciously accepted.

    Reading it from the environment keeps a deliberate partial build
    explicit and greppable — ALLOW_PARTIAL_CORPUS=1 in a deploy config —
    instead of someone editing this module to get past the gate.
    '''
    return os.environ.get(ALLOW_PARTIAL_CORPUS_ENV, '').strip().lower() in _TRUTHY

def download_source_documents(allow_partial: bool = False):
    downloader = PDFDownloader()
    results = downloader.download_documents()
    if results['failed']:
        shortfall = (f"{results['failed']}/{results['total']} source documents "
                     f"failed to download")
        if not allow_partial:
            raise RuntimeError(shortfall)
        # Accepted, but never quietly: an index built on a short corpus
        # answers confidently from documents it does not have.
        logger.warning(
            "Building on a PARTIAL corpus: %s. Accepted because %s is set. "
            "Answers will be grounded in %s of %s source documents.",
            shortfall, ALLOW_PARTIAL_CORPUS_ENV,
            results['total'] - results['failed'], results['total'])
    return results

def process_source_documents(allow_partial: Optional[bool] = None):
    # A partial corpus must never reach the embedding stage silently: the
    # output would still look perfect while the index quietly misses
    # documents — the exact failure class the citation bug taught us about.
    #
    # The gate can be opened deliberately, never accidentally: pass
    # allow_partial=True, or set ALLOW_PARTIAL_CORPUS in the environment.
    if allow_partial is None:
        allow_partial = allow_partial_from_env()
    download_source_documents(allow_partial=allow_partial)
    from .vector_store import vectordb
    documents_loader = PDFLoader()
    documents = documents_loader.load_documents()
    chunk_size = 1500
    chunk_overlap = 100
    splitter = DocumentSplitter(
        documents=documents, 
        chunk_size=chunk_size, 
        chunk_overlap=chunk_overlap)
    splitted_documents = splitter.split_documents()
    print("Documents loaded and splitted successfully...")
    
    vectordb.add_documents(splitted_documents)
    print("Chroma database setup completed.")

def clear_vector_store():
    path_to_vectorstore = "app/documents/vector_store/"
    try:
        # Use shutil.rmtree to remove the directory and its contents
        shutil.rmtree(path_to_vectorstore)
        print(f"Directory '{path_to_vectorstore}' and its contents have been permanently deleted.")
        time.sleep(3)
    except OSError as e:
        print(f"Error: {e}")
        
def reload_database(allow_partial: Optional[bool] = None):
    clear_vector_store()
    process_source_documents(allow_partial=allow_partial)
    
    

