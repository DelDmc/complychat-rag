from dotenv import load_dotenv
from typing import Any
import chromadb
from chromadb.config import Settings
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings

from .paths import CHROMA_DIR

load_dotenv()

# OpenAI caps an embeddings request at 300k tokens total. The default of 1000
# texts per request, at ~300 tokens per 1500-char chunk, lands right on that
# cap; 500 leaves room for the corpus to grow.
EMBEDDING_BATCH_SIZE = 500


def open_vectordb(persist_directory=CHROMA_DIR):
    '''The app's Chroma collection, persisted under persist_directory.

    reset_index.py builds a replacement index in a staging directory with
    this same function, so the index it checks is opened exactly the way the
    app opens it.
    '''
    persist_directory = str(persist_directory)
    # A fresh Settings each time: chromadb 0.4.3's PersistentClient mutates its
    # default Settings argument, so a second client in the same process would
    # repoint the first one's persist_directory.
    client = chromadb.PersistentClient(path=persist_directory, settings=Settings())
    return Chroma(
            collection_name='langchain',
            embedding_function=OpenAIEmbeddings(show_progress_bar=True,
                                                chunk_size=EMBEDDING_BATCH_SIZE),
            persist_directory=persist_directory,
            client=client
            )


# Anchored so running from any directory writes to (and only ever to) the
# same src/app/documents/vector_store/chroma directory.
vectordb = open_vectordb()
