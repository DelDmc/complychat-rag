import os
from unittest.mock import patch

from django.test import TestCase

from app.documents.pdf_loader import PDFLoader


class _StubCSVProcessor:
    '''Stand-in for CSVProcessor so tests never read the real CSV file.'''

    def __init__(self, processed_documents):
        self.processed_documents = processed_documents
        self.filenames_list = [row['filename'] for row in processed_documents]


class _FakeDocument:
    '''Minimal stand-in for a loaded document: just carries metadata.'''

    def __init__(self):
        self.metadata = {}


class _FakePDFMinerLoader:
    '''Fake PDFMinerLoader driven purely by filename.

    Any file whose basename appears in `fail_filenames` raises when loaded,
    mimicking an unreadable PDF; every other file yields `docs_per_file`
    placeholder documents.
    '''

    fail_filenames = set()
    docs_per_file = 1

    def __init__(self, file_path):
        self.file_path = file_path

    def load(self):
        if os.path.basename(self.file_path) in _FakePDFMinerLoader.fail_filenames:
            raise ValueError(f'Simulated unreadable PDF: {self.file_path}')
        return [_FakeDocument() for _ in range(_FakePDFMinerLoader.docs_per_file)]


# Four source rows; the second file is the one that fails to load in Test A.
CITATION_METADATA_FIX_DOCS = [
    {
        'filename': 'handbook.pdf',
        'name': 'FCA Handbook',
        'relevance': 'high',
        'link': 'https://www.fca.org.uk/handbook',
    },
    {
        'filename': 'broken.pdf',
        'name': 'Unreadable guidance',
        'relevance': 'medium',
        'link': 'https://www.fca.org.uk/broken',
    },
    {
        'filename': 'consultation.pdf',
        'name': 'Consultation paper',
        'relevance': 'low',
        'link': 'https://www.fca.org.uk/consultation',
    },
    {
        'filename': 'final-notice.pdf',
        'name': 'Final notice',
        'relevance': 'high',
        'link': 'https://www.fca.org.uk/final-notice',
    },
]


class CitationMetadataRegressionTests(TestCase):
    '''Regression tests for the citation-metadata fix in pdf_loader.

    The pre-fix code attached citation metadata to documents by list position
    after the load loop, so one unreadable PDF silently shifted every later
    citation onto the wrong source row. The fix binds metadata inside the
    load loop; these tests prove both behaviours.
    '''

    def setUp(self):
        _FakePDFMinerLoader.fail_filenames = set()
        _FakePDFMinerLoader.docs_per_file = 1
        self._stub_csv_processor = _StubCSVProcessor(CITATION_METADATA_FIX_DOCS)
        self._original_csv_processor = PDFLoader.CSV_processor
        PDFLoader.CSV_processor = self._stub_csv_processor
        # The pre-fix loader iterated this class attribute instead of
        # CSV_processor.processed_documents; keep it in step so the buggy
        # variant runs over the same four fake source files.
        self._original_documents_list = getattr(PDFLoader, 'documents_list', None)
        PDFLoader.documents_list = self._stub_csv_processor.filenames_list
        patcher = patch(
            'app.documents.pdf_loader.PDFMinerLoader', _FakePDFMinerLoader
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        PDFLoader.CSV_processor = self._original_csv_processor
        if self._original_documents_list is None:
            del PDFLoader.documents_list
        else:
            PDFLoader.documents_list = self._original_documents_list

    def test_failed_load_does_not_shift_citation_metadata(self):
        # The second source file fails to load; the remaining documents must
        # each carry the citation metadata of their own source row.
        _FakePDFMinerLoader.fail_filenames = {'broken.pdf'}

        documents = PDFLoader().load_documents()

        self.assertEqual(3, len(documents))
        expected_rows = [
            CITATION_METADATA_FIX_DOCS[0],
            CITATION_METADATA_FIX_DOCS[2],
            CITATION_METADATA_FIX_DOCS[3],
        ]
        for document, source_row in zip(documents, expected_rows):
            with self.subTest(source_row=source_row['filename']):
                self.assertEqual(source_row['name'], document.metadata['name'])
                self.assertEqual(
                    source_row['relevance'], document.metadata['relevance']
                )
                self.assertEqual(source_row['link'], document.metadata['link'])

    def test_multi_document_pdf_gets_same_source_metadata(self):
        # A loader may return several documents for one PDF; every one of
        # them must carry the citation metadata of that PDF's source row.
        _FakePDFMinerLoader.docs_per_file = 2

        documents = PDFLoader().load_documents()

        self.assertEqual(8, len(documents))
        for index, document in enumerate(documents):
            source_row = CITATION_METADATA_FIX_DOCS[index // 2]
            with self.subTest(document_index=index):
                self.assertEqual(source_row['name'], document.metadata['name'])
                self.assertEqual(
                    source_row['relevance'], document.metadata['relevance']
                )
                self.assertEqual(source_row['link'], document.metadata['link'])
