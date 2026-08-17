from typing import List
from langchain.docstore.document import Document
from langchain.text_splitter import RecursiveCharacterTextSplitter


class DocumentSplitter:
    def __init__(
        self, 
        documents:List[Document],
        chunk_size: int, 
        chunk_overlap: int
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.documents = documents

    def split_documents(self) -> List[Document]:
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap
        )
        splitted_documents = text_splitter.split_documents(self.documents)
        return splitted_documents
