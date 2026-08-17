from dotenv import load_dotenv
from typing import Any
import chromadb
from langchain.vectorstores import Chroma
from langchain.embeddings.openai import OpenAIEmbeddings

load_dotenv()

persist_directory = 'app/documents/vector_store/chroma/'
client = chromadb.PersistentClient(path=persist_directory)

vectordb = Chroma(
            collection_name='langchain',
            embedding_function=OpenAIEmbeddings(show_progress_bar=True),
            persist_directory=persist_directory,
            client=client
            )

        
        
    
