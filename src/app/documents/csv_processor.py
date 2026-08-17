import csv
from typing import List, Dict

class CSVProcessor:
    CSV_DIR = 'app/documents/files/complyChat_sources.csv'
    # CSV_DIR = 'app/documents/files/TEST_source.csv'

    def __init__(self):
        self.processed_documents: List[Dict[str, str]] = []
        self.filenames_list: List[str] = []
        
        self.process_csv()
    
    def process_csv(self):
        with open(self.CSV_DIR, mode='r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                self.filenames_list.append(row['filename'])
                self.processed_documents.append(
                    {'filename':row['filename'], 
                     'name':row['name'], 
                     'relevance':row['relevance'], 
                     'link':row['link']
                     }
                )   

