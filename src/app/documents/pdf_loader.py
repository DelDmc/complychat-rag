from tabulate import tabulate
from typing import Dict, List
import os

from langchain.docstore.document import Document
from langchain.document_loaders.pdf import PDFMinerLoader

from .csv_processor import CSVProcessor
from .paths import APP_DOCS_DIR

class PDFLoader:
    # Anchored in app/documents/paths.py so it cannot drift from the path
    # PDFDownloader writes into.
    APP_DOCS_DIR :str = str(APP_DOCS_DIR)
    CSV_processor :CSVProcessor = CSVProcessor()

    def load_documents(self) -> List[Document]:
        source_rows :List[Dict[str, str]] = PDFLoader.CSV_processor.processed_documents
        total_documents = len(source_rows)
        loaded_documents = 0
        failed_documents = 0

        documents = []
        for source_row in source_rows:
            document_path = os.path.join(PDFLoader.APP_DOCS_DIR, source_row['filename'])
            print(f"Now loading {document_path}...")

            try:
                loader = PDFMinerLoader(document_path)
                loaded = loader.load()
                # Attach the citation metadata now, while the row describing
                # this file is in hand. Matching by position after the loop
                # drifts the moment one file fails to load.
                for document in loaded:
                    modify_metadata_source(document, source_row)
                documents.extend(loaded)
                loaded_documents += 1

            except Exception as e:
                print(f"Failed to load {document_path}: {e}")
                failed_documents += 1

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