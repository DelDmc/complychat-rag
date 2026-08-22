from dotenv import load_dotenv
from typing import Any
import chromadb
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings

from .paths import CHROMA_DIR

load_dotenv()

# Anchored so running from any directory writes to (and only ever to) the
# same src/app/documents/vector_store/chroma directory.
persist_directory = str(CHROMA_DIR)
client = chromadb.PersistentClient(path=persist_directory)

vectordb = Chroma(
            collection_name='langchain',
            embedding_function=OpenAIEmbeddings(show_progress_bar=True),
            persist_directory=persist_directory,
            client=client
            )

        
        
    
