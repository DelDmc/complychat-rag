from dotenv import load_dotenv
from .pdf_loader import PDFLoader
from .document_splitter import DocumentSplitter
from .pdf_downloader import PDFDownloader

import shutil
import time

load_dotenv()

def download_source_documents(allow_partial: bool = False):
    downloader = PDFDownloader()
    results = downloader.download_documents()
    if results['failed'] and not allow_partial:
        raise RuntimeError(
            f"{results['failed']}/{results['total']} source documents "
            f"failed to download"
        )
    return results

def process_source_documents():
    # A partial corpus must never reach the embedding stage silently: the
    # output would still look perfect while the index quietly misses
    # documents — the exact failure class the citation bug taught us about.
    download_source_documents()
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
        
def reload_database():
    clear_vector_store()
    process_source_documents()
    
    

