'''Tests for the ingestion pipeline: citation metadata, and the corpus
downloader that feeds it.

Two suites live here.

`CitationMetadataRegressionTests` covers the loader-side bug this project
is named for: source metadata was bound to documents by list position,
after a loop that skips files which fail to load, so one unreadable PDF
shifted every later citation onto the wrong regulation.

Everything from `_FakeResponse` onwards covers the downloader and the
ingestion gate, stubbed at the HTTP boundary.

Nothing here needs the network, an API key, fixtures on disk, or the real
sources CSV. The tests follow the repo's unittest/Django convention and use
SimpleTestCase because none of the code under test touches the ORM.
'''

import os
import tempfile
from io import StringIO
from unittest import mock
from unittest.mock import patch

import requests
from django.test import SimpleTestCase

from app.documents import pdf_downloader, process_documents
from app.documents.pdf_downloader import PDFDownloader
from app.documents.pdf_loader import PDFLoader


# ---------------------------------------------------------------------------
# Loader side: citation metadata must follow its own source row.
# ---------------------------------------------------------------------------

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


class CitationMetadataRegressionTests(SimpleTestCase):
    '''Regression tests for the citation-metadata fix in pdf_loader.

    The pre-fix code attached citation metadata to documents by list position
    after the load loop, so one unreadable PDF silently shifted every later
    citation onto the wrong source row. The fix binds metadata inside the
    load loop; these tests prove both behaviours.
    '''

    def setUp(self):
        # Every restoration is registered on addCleanup immediately after the
        # corresponding mutation. tearDown alone is not crash-safe: if a later
        # mutation in setUp raises, unittest skips tearDown and the class-level
        # stubs leak into every subsequent test in the process.
        _FakePDFMinerLoader.fail_filenames = set()
        _FakePDFMinerLoader.docs_per_file = 1

        self._stub_csv_processor = _StubCSVProcessor(CITATION_METADATA_FIX_DOCS)
        original_csv_processor = PDFLoader.CSV_processor
        PDFLoader.CSV_processor = self._stub_csv_processor
        self.addCleanup(
            lambda: setattr(PDFLoader, 'CSV_processor', original_csv_processor)
        )

        # The pre-fix loader iterated this class attribute instead of
        # CSV_processor.processed_documents; keep it in step so the buggy
        # variant runs over the same four fake source files.
        original_documents_list = getattr(PDFLoader, 'documents_list', None)
        PDFLoader.documents_list = self._stub_csv_processor.filenames_list

        def restore_documents_list():
            if original_documents_list is None:
                del PDFLoader.documents_list
            else:
                PDFLoader.documents_list = original_documents_list

        self.addCleanup(restore_documents_list)

        patcher = patch(
            'app.documents.pdf_loader.PDFMinerLoader', _FakePDFMinerLoader
        )
        self.addCleanup(patcher.stop)
        patcher.start()

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


# ---------------------------------------------------------------------------
# Downloader side: fetching the corpus, and the gate in front of embedding.
# ---------------------------------------------------------------------------

class _FakeResponse:
    '''Minimal stand-in for requests.Response used in streaming mode.'''

    def __init__(self, status_code=200, chunks=()):
        self.status_code = status_code
        self._chunks = list(chunks)

    def iter_content(self, chunk_size=None):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False


class _StubSession:
    '''Records every requested URL and replays canned responses in order.

    ``responses`` maps a URL to a list of outcomes; each call consumes the
    next entry (or repeats the last one once the list is exhausted).
    '''

    def __init__(self, responses):
        self.responses = responses
        self.requested_urls = []

    def get(self, url, stream=False, timeout=None):
        self.requested_urls.append(url)
        outcomes = self.responses[url]
        outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _pdf_body():
    return [b'%PDF-1.4 fake pdf bytes']


def _html_body():
    return [b'<html><body>landing page</body></html>']


ROW_ONE_LINK = 'https://www.fca.org.uk/a-live-link'
ROW_TWO_LINK = 'https://www.handbook.fca.org.uk/b-needs-fallback'


class PDFDownloaderTestBase(SimpleTestCase):
    '''Shared plumbing: a real temp directory plus CSV stubbing.'''

    SOURCE_ROWS = [
        {
            'filename': 'a_live_link.pdf',
            'name': 'A live link',
            'relevance': 'high',
            'link': ROW_ONE_LINK,
        },
        {
            'filename': 'b_needs_fallback.pdf',
            'name': 'B needs fallback',
            'relevance': 'medium',
            'link': ROW_TWO_LINK,
        },
    ]

    def setUp(self):
        super().setUp()
        # Redirect the anchored corpus directory into a temp directory so
        # the tests never touch the real one.
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        patcher = mock.patch.object(
            PDFDownloader, 'APP_DOCS_DIR', self._tmp_dir.name
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_downloader(self, session):
        downloader = PDFDownloader.__new__(PDFDownloader)
        downloader.session = session
        stub_csv = mock.Mock()
        stub_csv.processed_documents = [dict(row) for row in self.SOURCE_ROWS]
        downloader.csv_processor = stub_csv
        return downloader

    def _write_corpus_file(self, filename, body=b'%PDF-1.4 already downloaded'):
        path = os.path.join(self._tmp_dir.name, filename)
        with open(path, 'wb') as corpus_file:
            corpus_file.write(body)
        return path


class IsPdfFileTests(PDFDownloaderTestBase):
    '''_is_pdf_file accepts only non-empty %PDF- signed files.'''

    def test_accepts_pdf_magic_bytes(self):
        path = self._write_corpus_file('real.pdf', b'%PDF-1.7 ...')
        self.assertTrue(PDFDownloader._is_pdf_file(path))

    def test_rejects_empty_file(self):
        path = self._write_corpus_file('empty.pdf', b'')
        self.assertFalse(PDFDownloader._is_pdf_file(path))

    def test_rejects_html_body(self):
        path = self._write_corpus_file(
            'page.html', b'<html><body>not a pdf</body></html>')
        self.assertFalse(PDFDownloader._is_pdf_file(path))


class DownloadOnceTests(PDFDownloaderTestBase):
    '''_download_once keeps only genuine PDF bodies and leaves no debris.'''

    def test_non_pdf_body_leaves_no_part_and_no_destination(self):
        destination = os.path.join(self._tmp_dir.name, 'out.pdf')
        session = _StubSession({
            'https://example.test/page': [_FakeResponse(chunks=_html_body())],
        })
        downloader = self._make_downloader(session)

        succeeded, reason = downloader._download_once(
            session, 'https://example.test/page', destination)

        self.assertFalse(succeeded)
        self.assertIn('not a PDF', reason)
        self.assertFalse(os.path.exists(destination + '.part'))
        self.assertFalse(os.path.exists(destination))

    def test_http_404_fails_without_writing_anything(self):
        destination = os.path.join(self._tmp_dir.name, 'missing.pdf')
        session = _StubSession({
            'https://example.test/404': [_FakeResponse(status_code=404)],
        })
        downloader = self._make_downloader(session)

        succeeded, reason = downloader._download_once(
            session, 'https://example.test/404', destination)

        self.assertFalse(succeeded)
        self.assertEqual('HTTP 404', reason)
        self.assertFalse(os.path.exists(destination))

    def test_successful_download_promotes_part_file_to_destination(self):
        destination = os.path.join(self._tmp_dir.name, 'good.pdf')
        session = _StubSession({
            'https://example.test/good': [_FakeResponse(chunks=_pdf_body())],
        })
        downloader = self._make_downloader(session)

        succeeded, reason = downloader._download_once(
            session, 'https://example.test/good', destination)

        self.assertTrue(succeeded)
        self.assertEqual('downloaded', reason)
        self.assertTrue(os.path.exists(destination))
        self.assertFalse(os.path.exists(destination + '.part'))

    def test_response_larger_than_cap_is_aborted(self):
        destination = os.path.join(self._tmp_dir.name, 'huge.pdf')
        session = _StubSession({
            'https://example.test/huge': [
                _FakeResponse(chunks=[b'x' * 65536] * 4),
            ],
        })
        downloader = self._make_downloader(session)

        # The cap is patched down to 100 KB so the test streams a few
        # hundred KB instead of writing a 200 MB file.
        with mock.patch.object(PDFDownloader, 'MAX_DOWNLOAD_BYTES', 100_000):
            succeeded, reason = downloader._download_once(
                session, 'https://example.test/huge', destination)

        self.assertFalse(succeeded)
        self.assertIn('byte limit', reason)
        self.assertFalse(os.path.exists(destination))
        # An abort must leave nothing behind either: the cap exists to bound
        # damage from a misbehaving host, and a stranded .part does not.
        self.assertFalse(os.path.exists(destination + '.part'))


class DownloadWithRetryTests(PDFDownloaderTestBase):
    '''Retry policy: transient failures retry, permanent ones fail fast.'''

    def test_permanent_failure_is_not_retried(self):
        # A 404 will answer identically next time; a second attempt is
        # guaranteed-useless waiting in the Docker build path.
        session = _StubSession({
            'https://example.test/gone': [
                _FakeResponse(status_code=404),
                _FakeResponse(status_code=404),
            ],
        })
        downloader = self._make_downloader(session)

        destination = os.path.join(self._tmp_dir.name, 'gone.pdf')
        succeeded, reason = downloader._download_with_retry(
            session, 'https://example.test/gone', destination)

        self.assertFalse(succeeded)
        self.assertEqual('HTTP 404', reason)
        self.assertEqual(1, len(session.requested_urls),
                         'a 404 must not be retried')

    def test_non_pdf_body_is_not_retried(self):
        # An HTML landing page is a permanent answer too: the fallback list,
        # not a blind second attempt, is the right response to it.
        session = _StubSession({
            'https://example.test/page': [
                _FakeResponse(chunks=_html_body()),
                _FakeResponse(chunks=_html_body()),
            ],
        })
        downloader = self._make_downloader(session)

        destination = os.path.join(self._tmp_dir.name, 'page.pdf')
        succeeded, reason = downloader._download_with_retry(
            session, 'https://example.test/page', destination)

        self.assertFalse(succeeded)
        self.assertEqual(1, len(session.requested_urls),
                         'a non-PDF body must not be retried')

    def test_transient_server_error_is_retried_then_succeeds(self):
        session = _StubSession({
            'https://example.test/flaky': [
                _FakeResponse(status_code=503),
                _FakeResponse(chunks=_pdf_body()),
            ],
        })
        downloader = self._make_downloader(session)

        destination = os.path.join(self._tmp_dir.name, 'flaky.pdf')
        with mock.patch.object(pdf_downloader.time, 'sleep'):
            succeeded, reason = downloader._download_with_retry(
                session, 'https://example.test/flaky', destination)

        self.assertTrue(succeeded)
        self.assertEqual(2, len(session.requested_urls),
                         'a 503 deserves exactly one retry')

    def test_connection_error_is_treated_as_transient_and_retried(self):
        session = _StubSession({
            'https://example.test/unreachable': [
                requests.exceptions.ConnectionError('connection reset'),
                requests.exceptions.ConnectionError('connection reset'),
                requests.exceptions.ConnectionError('connection reset'),
            ],
        })
        downloader = self._make_downloader(session)

        destination = os.path.join(self._tmp_dir.name, 'unreachable.pdf')
        with mock.patch.object(pdf_downloader.time, 'sleep'):
            succeeded, reason = downloader._download_with_retry(
                session, 'https://example.test/unreachable', destination)

        self.assertFalse(succeeded)
        self.assertIn('request error', reason)
        self.assertEqual(PDFDownloader.MAX_ATTEMPTS_PER_URL,
                         len(session.requested_urls))

    def test_first_failure_reason_survives_fallback_attempts(self):
        # The live FCA link returns an HTML shell; the fallback then fails
        # too. The report must name the live link's failure, not the
        # fallback's — otherwise it hides why the primary source failed.
        session = _StubSession({
            ROW_TWO_LINK: [_FakeResponse(chunks=_html_body())],
            'http://web.archive.org/fallback-copy': [
                _FakeResponse(status_code=404),
            ],
        })
        downloader = self._make_downloader(session)

        destination = os.path.join(self._tmp_dir.name, 'fallback.pdf')
        with mock.patch.object(pdf_downloader.time, 'sleep'):
            succeeded, reason = downloader._download_with_retry(
                session, ROW_TWO_LINK, destination,
                fallback_urls=['http://web.archive.org/fallback-copy'])

        self.assertFalse(succeeded)
        self.assertIn('not a PDF', reason)
        self.assertEqual(2, len(session.requested_urls),
                         'fallback must still be tried once')


class FallbackOrderingTests(PDFDownloaderTestBase):
    '''The CSV link is tried first; fallbacks engage only after it fails.'''

    FALLBACK_URL = 'http://web.archive.org/fallback-copy'

    def _run_download(self, row_two_outcomes, fallback_outcomes=None):
        responses = {
            ROW_ONE_LINK: [_FakeResponse(chunks=_pdf_body())],
            ROW_TWO_LINK: list(row_two_outcomes),
        }
        if fallback_outcomes is not None:
            responses[self.FALLBACK_URL] = fallback_outcomes
        session = _StubSession(responses)
        downloader = self._make_downloader(session)
        with mock.patch.dict(
            PDFDownloader.FALLBACK_URLS,
            {'b_needs_fallback.pdf': [self.FALLBACK_URL]},
        ), mock.patch.object(pdf_downloader.time, 'sleep'):
            results = downloader.download_documents(force=True)
        return results, session

    def test_csv_link_tried_before_fallback(self):
        results, session = self._run_download(
            [_FakeResponse(chunks=_pdf_body())])

        self.assertEqual(0, results['failed'])
        self.assertNotIn(self.FALLBACK_URL, session.requested_urls)

    def test_fallback_engages_only_after_csv_link_fails(self):
        results, session = self._run_download(
            [_FakeResponse(chunks=_html_body())],          # live CSV link fails
            fallback_outcomes=[_FakeResponse(chunks=_pdf_body())],  # ...fallback succeeds
        )

        self.assertEqual(0, results['failed'])
        self.assertLess(
            session.requested_urls.index(ROW_TWO_LINK),
            session.requested_urls.index(self.FALLBACK_URL),
            'the fallback must come after the CSV link has failed')


class SkipBehaviourTests(PDFDownloaderTestBase):
    '''Existing valid PDFs are skipped without touching the network.'''

    def test_existing_valid_pdfs_make_zero_session_calls_unless_forced(self):
        self._write_corpus_file('a_live_link.pdf')
        self._write_corpus_file('b_needs_fallback.pdf')

        session = _StubSession({
            ROW_ONE_LINK: [_FakeResponse(chunks=_pdf_body())],
            ROW_TWO_LINK: [_FakeResponse(chunks=_pdf_body())],
        })
        downloader = self._make_downloader(session)

        results = downloader.download_documents(force=False)

        self.assertEqual([], session.requested_urls)
        self.assertEqual(2, results['skipped'])

        with mock.patch.object(pdf_downloader.time, 'sleep'):
            forced_results = downloader.download_documents(force=True)
        self.assertEqual(2, len(session.requested_urls))
        self.assertEqual(0, forced_results['skipped'])

    def test_second_full_run_completes_without_sleeping_between_rows(self):
        # Task 4: re-running over a complete corpus must make no network
        # calls AND pay no politeness delay. Sleep is patched to blow up if
        # the skip path ever tries to nap again.
        self._write_corpus_file('a_live_link.pdf')
        self._write_corpus_file('b_needs_fallback.pdf')

        session = _StubSession({})
        downloader = self._make_downloader(session)

        def fail_if_called(*args, **kwargs):
            raise AssertionError('sleep must not fire when nothing was fetched')

        with mock.patch.object(pdf_downloader.time, 'sleep', fail_if_called):
            results = downloader.download_documents()

        self.assertEqual(len(self.SOURCE_ROWS), results['skipped'])
        self.assertEqual(0, results['failed'])


class IngestionGateTests(SimpleTestCase):
    '''Task 3: a partial corpus must fail loudly before any embedding.

    These drive process_source_documents() end to end with every stage
    after the download gate stubbed out.
    '''

    SOURCE_ROWS = PDFDownloaderTestBase.SOURCE_ROWS

    def setUp(self):
        super().setUp()
        self._tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp_dir.cleanup)
        patcher = mock.patch.object(
            PDFDownloader, 'APP_DOCS_DIR', self._tmp_dir.name
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _make_downloader(self, session):
        downloader = PDFDownloader.__new__(PDFDownloader)
        downloader.session = session
        stub_csv = mock.Mock()
        stub_csv.processed_documents = [dict(row) for row in self.SOURCE_ROWS]
        downloader.csv_processor = stub_csv
        return downloader

    def _patch_downstream_stages(self, loader):
        '''Stub everything from loading onwards, vector store included.'''
        fake_loader_factory = mock.Mock()
        fake_loader_factory.return_value = loader
        fake_splitter = mock.Mock()
        fake_splitter.split_documents.return_value = []
        return [
            mock.patch.dict('sys.modules', {
                'app.documents.vector_store': mock.MagicMock(),
            }),
            mock.patch.object(process_documents, 'PDFLoader',
                              fake_loader_factory),
            mock.patch.object(process_documents, 'DocumentSplitter',
                              lambda **kwargs: fake_splitter),
        ]

    def test_partial_corpus_raises_and_never_reaches_embedding(self):
        # One row downloads fine; the other hits an HTML landing page that
        # no fallback can rescue. Nothing may be embedded afterwards.
        session = _StubSession({
            ROW_ONE_LINK: [_FakeResponse(chunks=_pdf_body())],
            ROW_TWO_LINK: [_FakeResponse(chunks=_html_body())],
        })
        downloader = self._make_downloader(session)

        # If the pipeline ever got past the gate this would blow up.
        sentinel_loader = mock.Mock()
        sentinel_loader.load_documents.side_effect = AssertionError(
            'embedding stage must not run on a partial corpus')

        patches = self._patch_downstream_stages(sentinel_loader)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch.object(process_documents, 'PDFDownloader',
                               lambda: downloader), \
               mock.patch.object(process_documents.time, 'sleep'):
            with self.assertRaises(RuntimeError) as caught:
                process_documents.process_source_documents()

        self.assertIn('1/2 source documents failed to download',
                      str(caught.exception))

    def _partial_corpus_downloader(self):
        # One row downloads fine; the other hits an HTML landing page that
        # no fallback can rescue — the shape of the 4 always-dead CSV rows.
        session = _StubSession({
            ROW_ONE_LINK: [_FakeResponse(chunks=_pdf_body())],
            ROW_TWO_LINK: [_FakeResponse(chunks=_html_body())],
        })
        return self._make_downloader(session)

    def test_partial_corpus_is_allowed_when_explicitly_accepted(self):
        # Task 16: the gate stays shut by default but must be openable on
        # purpose, or a corpus with permanently dead rows can never be
        # built at all.
        downloader = self._partial_corpus_downloader()

        reached_embedding = mock.Mock()
        reached_embedding.load_documents.return_value = []
        patches = self._patch_downstream_stages(reached_embedding)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        with mock.patch.object(process_documents, 'PDFDownloader',
                               lambda: downloader), \
               mock.patch.object(process_documents.time, 'sleep'), \
               mock.patch.object(pdf_downloader.time, 'sleep'):
            with self.assertLogs(process_documents.logger, 'WARNING') as logged:
                process_documents.process_source_documents(allow_partial=True)

        # It proceeds, and it says so loudly: a short corpus that embeds
        # silently is the failure this whole gate exists to prevent.
        reached_embedding.load_documents.assert_called_once_with()
        self.assertIn('PARTIAL corpus', logged.output[0])
        self.assertIn('1/2 source documents failed to download',
                      logged.output[0])

    def test_env_var_opens_the_gate_without_an_argument(self):
        # The deploy-time hatch: ALLOW_PARTIAL_CORPUS makes a deliberate
        # reduced build explicit and greppable instead of a source edit.
        downloader = self._partial_corpus_downloader()

        reached_embedding = mock.Mock()
        reached_embedding.load_documents.return_value = []
        patches = self._patch_downstream_stages(reached_embedding)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

        with mock.patch.dict(os.environ, {'ALLOW_PARTIAL_CORPUS': '1'}), \
               mock.patch.object(process_documents, 'PDFDownloader',
                                 lambda: downloader), \
               mock.patch.object(process_documents.time, 'sleep'), \
               mock.patch.object(pdf_downloader.time, 'sleep'):
            with self.assertLogs(process_documents.logger, 'WARNING'):
                process_documents.process_source_documents()

        reached_embedding.load_documents.assert_called_once_with()

    def test_env_var_values_that_must_not_open_the_gate(self):
        for value in ('', '0', 'false', 'no', 'maybe'):
            with self.subTest(value=value):
                with mock.patch.dict(os.environ,
                                     {'ALLOW_PARTIAL_CORPUS': value}):
                    self.assertFalse(process_documents.allow_partial_from_env())
        with mock.patch.dict(os.environ, {'ALLOW_PARTIAL_CORPUS': 'TRUE '}):
            self.assertTrue(process_documents.allow_partial_from_env())

    def test_complete_corpus_passes_the_gate(self):
        session = _StubSession({
            ROW_ONE_LINK: [_FakeResponse(chunks=_pdf_body())],
            ROW_TWO_LINK: [_FakeResponse(chunks=_pdf_body())],
        })
        downloader = self._make_downloader(session)

        quiet_loader = mock.Mock()
        quiet_loader.load_documents.return_value = []
        patches = self._patch_downstream_stages(quiet_loader)
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        with mock.patch.object(process_documents, 'PDFDownloader',
                               lambda: downloader), \
               mock.patch.object(process_documents.time, 'sleep'):
            # Must not raise: a complete corpus may proceed to (stubbed)
            # embedding.
            process_documents.process_source_documents()


class DisplaySummaryTests(PDFDownloaderTestBase):
    '''The summary table renders its counts.'''

    def test_display_summary_prints_counts(self):
        from app.documents.pdf_downloader import display_summary
        output = StringIO()
        with mock.patch('sys.stdout', output):
            display_summary(43, 39, 0, 4)
        rendered = output.getvalue()
        self.assertIn('Total', rendered)
        self.assertIn('Downloaded', rendered)
        self.assertIn('Fail', rendered)
