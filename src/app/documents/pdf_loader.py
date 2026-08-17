from tabulate import tabulate
from typing import List
import os

from langchain.docstore.document import Document
from langchain.document_loaders.pdf import PDFMinerLoader

from .csv_processor import CSVProcessor

class PDFLoader:
    APP_DOCS_DIR :str = 'app/documents/files/comply_sources'
    CSV_processor :CSVProcessor = CSVProcessor()
    documents_list :List[str] = CSV_processor.filenames_list 
    
    def load_documents(self) -> List[Document]:
        total_documents = len(PDFLoader.documents_list)
        loaded_documents = 0
        failed_documents = 0
        
        documents = []
        for document_filename in PDFLoader.documents_list:
            document_path = os.path.join(PDFLoader.APP_DOCS_DIR, document_filename)
            print(f"Now loading {document_path}...")

            try:
                loader = PDFMinerLoader(document_path)
                documents.extend(loader.load())
                loaded_documents += 1
                
            except Exception as e:
                print(f"Failed to load {document_path}: {e}")
                failed_documents += 1
        
        # Process the loaded documents
        for idx, document in enumerate(documents):
            modify_metadata_source(document, self.CSV_processor.processed_documents[idx])
        
        display_summary(total_documents, loaded_documents, failed_documents)
        return documents
    
def modify_metadata_source(document, dict_document):
    '''Link data from source csv to document metadata return by PDF loader'''
    document.metadata['name'] = dict_document['name'] 
    document.metadata['relevance'] = dict_document['relevance'] 
    document.metadata['link'] =  dict_document['link'] 

def display_summary(given, loaded, failed):
    headers = ["Total", "Success", "Fail"]
    data = [[given, loaded, failed]]
    
    table = tabulate(data, headers=headers, tablefmt="pretty")
    print("-" * 26)
    print("Processed Documents")
    print(table)