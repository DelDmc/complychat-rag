'''Download the public source documents listed in complyChat_sources.csv.

The corpus itself is not vendored in the repository; this step fetches each
public URL from the sources CSV into ``app/documents/files/comply_sources``
using the exact ``filename`` recorded in the CSV, so that ``PDFLoader`` can
pick the files up afterwards during ``process_source_documents``.

Usage (run from the ``src`` directory):

    python -m app.documents.pdf_downloader [--force]

Requests are made sequentially and politely, with a timeout. Only transient
problems (timeouts, connection errors, HTTP 5xx) are retried; permanent
failures such as HTTP 404 or a non-PDF response body fail immediately.
Only files whose body starts with the ``%PDF-`` magic bytes are kept, so
error pages are never written into the corpus directory.

Two groups of CSV links cannot be fetched directly by a programmatic
client:

* ``handbook.fca.org.uk`` now serves an Angular application shell for its
  legacy ``.pdf`` paths; genuine archived copies of those PDFs are fetched
  from the Internet Archive's Wayback Machine instead.
* ``legislation.gov.uk`` sits behind an AWS WAF challenge that answers
  HTTP 202 to non-browser clients. Where an equivalent static PDF exists
  on the same site it is used; otherwise an archived copy is fetched.

Each fallback is keyed by the CSV ``filename`` and was verified to return
a real PDF at the time of writing. The original CSV link is always tried
first, so the fallback only engages when the live source still fails.
'''

import argparse
import os
import time
from typing import Dict, List, Optional, Tuple

import requests
from requests import exceptions as requests_exceptions
from tabulate import tabulate

from .csv_processor import CSVProcessor
from .paths import APP_DOCS_DIR


class PDFDownloader:
    # Anchored in app/documents/paths.py so it cannot drift from the path
    # PDFLoader reads, and so CWD stops mattering.
    APP_DOCS_DIR: str = str(APP_DOCS_DIR)

    # Abort a download that streams past this size; no source document in the
    # corpus is anywhere near it and it bounds damage from a misbehaving host.
    MAX_DOWNLOAD_BYTES: int = 200 * 1024 * 1024

    # Be patient with slow regulator websites, but never hang forever.
    REQUEST_TIMEOUT_SECONDS: Tuple[int, int] = (10, 60)
    RETRY_DELAY_SECONDS: int = 3
    INTER_REQUEST_DELAY_SECONDS: float = 1.0
    MAX_ATTEMPTS_PER_URL: int = 2

    USER_AGENT: str = (
        'Mozilla/5.0 (compatible; ComplyChat-corpus-ingestion/1.0; '
        '+https://github.com/DelDmc/complychat-rag)'
    )

    # Verified alternative sources for rows whose live link is unusable from
    # a programmatic client (SPA shell or WAF challenge).
    #
    # KEYS TRACK THE CSV `filename` COLUMN. Renaming a filename in
    # complyChat_sources.csv without renaming the key here silently drops
    # that row's fallback; swapping two filenames silently points each
    # fallback at the wrong document, so the file's content and its
    # citation would disagree with nothing to catch it.
    FALLBACK_URLS: Dict[str, List[str]] = {
        # handbook.fca.org.uk serves an SPA shell for .pdf paths; use the
        # Internet Archive's copies of the genuine PDFs.
        'Banking_Conduct_of_Business_sourcebook_BCOBS.pdf': [
            'http://web.archive.org/web/20240209160746id_/https://www.handbook.fca.org.uk/handbook/BCOBS.pdf',
        ],
        'Conduct_of_Business_sourcebook_COBS_Сhapter_4_Communicating_with_clients__including_financial_promotions.pdf': [
            'http://web.archive.org/web/20231208220326id_/https://www.handbook.fca.org.uk/handbook/COBS/4.pdf',
        ],
        'Dispute_resolution__Complaints_For_PSPs.pdf': [
            'http://web.archive.org/web/20240526123119id_/https://www.handbook.fca.org.uk/handbook/DISP/1.pdf',
        ],
        'Dispute_Resolution_Complaints_sourcebook_DISP.pdf': [
            'http://web.archive.org/web/20231208224317id_/https://www.handbook.fca.org.uk/handbook/DISP.pdf',
        ],
        'FCA_Enforcement_Guide_EG.pdf': [
            'http://web.archive.org/web/20230918123107id_/https://www.handbook.fca.org.uk/handbook/EG.pdf',
        ],
        'FCA_financial_crime_guide_FCG.pdf': [
            'http://web.archive.org/web/20230224144746id_/https://www.handbook.fca.org.uk/handbook/FCG.pdf',
        ],
        'FCA_Wind_down_planning_guide.pdf': [
            'http://web.archive.org/web/20240421092021id_/https://www.handbook.fca.org.uk/handbook/WDPG.pdf',
        ],
        'Principles_for_Business_PRIN_Chapters_1_3.pdf': [
            'http://web.archive.org/web/20230508055306id_/https://www.handbook.fca.org.uk/handbook/PRIN.pdf',
        ],
        'SUP_Chapter_15_14__Notifications_under_the_Payment_Services_Regulations_.pdf': [
            'http://web.archive.org/web/20240522183113id_/https://www.handbook.fca.org.uk/handbook/SUP/15/14.pdf',
        ],
        'The_Perimeter_Guidance_manual_PERG_Chapter_2_Authorisation_and_regulated_activities.pdf': [
            'http://web.archive.org/web/20230321164141id_/https://www.handbook.fca.org.uk/handbook/PERG/2.pdf',
        ],
        'The_Perimeter_Guidance_manual_PERG_Chapter_3A_Guidance_on_the_scope_of_the_Electronic_Money_Regulations_2011.pdf': [
            'http://web.archive.org/web/20240415042459id_/https://www.handbook.fca.org.uk/handbook/PERG/3A.pdf',
        ],
        'The_Perimeter_Guidance_manual_PERG_Chapter_8__Financial_promotion_and_related_activities.pdf': [
            'http://web.archive.org/web/20240130164322id_/https://www.handbook.fca.org.uk/handbook/PERG/8.pdf',
        ],
        'The_Perimeter_Guidance_manual_PERG_Chapter_15_Guidance_on_the_scope_of_Payment_Services_Regulations_2017.pdf': [
            'http://web.archive.org/web/20231210002731id_/https://www.handbook.fca.org.uk/handbook/PERG/15.pdf',
        ],
        'Unfair_contract_terms_and_Consumer_Notices_Regulatory_guide.pdf': [
            'http://web.archive.org/web/20240414103048id_/https://www.handbook.fca.org.uk/handbook/UNFCOG/1.pdf',
        ],
        # legislation.gov.uk is behind an AWS WAF challenge; prefer the
        # static as-enacted PDF on the same site where one exists.
        'Financial_Services_and_Markets_Act_2000.pdf': [
            'https://www.legislation.gov.uk/ukpga/2000/8/pdfs/ukpga_20000008_en.pdf',
        ],
        'The_Electronic_Money_Regulations_2011.pdf': [
            'https://www.legislation.gov.uk/uksi/2011/99/pdfs/uksi_20110099_en.pdf',
        ],
        'The_Financial_Services_and_Markets_Act_2000_Financial_Promotion_Order_2005.pdf': [
            'https://www.legislation.gov.uk/uksi/2005/1529/pdfs/uksi_20051529_en.pdf',
        ],
        # No static as-enacted PDF exists for these three SIs; use archived
        # copies of the dynamically generated PDFs.
        'The_Money_Laundering__Terrorist_Financing_and_Transfer_of_Funds_Information_on_the_Payer_Regulations_2017.pdf': [
            'http://web.archive.org/web/20240127225005id_/https://www.legislation.gov.uk/uksi/2017/692/data.pdf',
        ],
        'The_Payment_and_Electronic_Money_Institution_Insolvency_Regulations_2021.pdf': [
            'http://web.archive.org/web/20251009023337id_/https://www.legislation.gov.uk/uksi/2021/716/2024-01-04/data.pdf',
        ],
        'The_Payment_Services_Regulations_2017.pdf': [
            'http://web.archive.org/web/20240218142140id_/https://www.legislation.gov.uk/uksi/2017/752/data.pdf',
        ],
    }

    def __init__(self, session: Optional[requests.Session] = None):
        self.csv_processor: CSVProcessor = CSVProcessor()
        self.session: requests.Session = session if session is not None \
            else self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        session.headers.update({
            'User-Agent': PDFDownloader.USER_AGENT,
            'Accept': 'application/pdf,*/*;q=0.8',
        })
        return session

    def download_documents(self, force: bool = False) -> Dict[str, int]:
        '''Fetch every source document referenced by the CSV.

        Files that are already present and look like valid PDFs are skipped
        unless ``force`` is set, so the step can safely be re-run.
        '''
        source_rows: List[Dict[str, str]] = self.csv_processor.processed_documents
        total_documents = len(source_rows)
        downloaded_documents = 0
        skipped_documents = 0
        failed_documents = 0
        failures: List[Tuple[str, str, str]] = []

        os.makedirs(PDFDownloader.APP_DOCS_DIR, exist_ok=True)

        for position, source_row in enumerate(source_rows, start=1):
            filename = source_row['filename']
            link = source_row['link']
            # basename() the CSV value before it becomes a path. The column
            # is trusted, so this is insurance rather than a fix, and it
            # pairs with the anchoring in paths.py.
            document_path = os.path.join(PDFDownloader.APP_DOCS_DIR,
                                         os.path.basename(filename))
            print(f"[{position}/{total_documents}] {filename}")
            print(f"    {link}")

            made_request = False
            if not force and self._is_pdf_file(document_path):
                print("    Already present and valid, skipping.")
                skipped_documents += 1
            else:
                made_request = True
                succeeded, reason = self._download_with_retry(
                    self.session, link, document_path,
                    PDFDownloader.FALLBACK_URLS.get(filename))
                if succeeded:
                    print("    Downloaded OK.")
                    downloaded_documents += 1
                else:
                    print(f"    FAILED: {reason}")
                    failed_documents += 1
                    failures.append((filename, link, reason))

            # Stay polite: pause only between rows that actually hit the
            # network, and never after the last one. Skipping a fully
            # downloaded corpus must cost no sleeping at all.
            if made_request and position < total_documents:
                time.sleep(PDFDownloader.INTER_REQUEST_DELAY_SECONDS)

        display_summary(total_documents, downloaded_documents,
                        skipped_documents, failed_documents)
        display_failures(failures)
        return {
            'total': total_documents,
            'downloaded': downloaded_documents,
            'skipped': skipped_documents,
            'failed': failed_documents,
        }

    def _download_with_retry(self, session: requests.Session, url: str,
                             destination: str,
                             fallback_urls: Optional[List[str]] = None
                             ) -> Tuple[bool, str]:
        '''Attempt a single download, retrying only transient failures,
        then trying any verified fallback sources before giving up.

        The first failure reason is kept for the report: with fallbacks in
        play the last candidate's error would otherwise hide why the live
        FCA link failed.'''
        first_reason = 'not attempted'
        candidate_urls = [url] + list(fallback_urls or [])
        for candidate_url in candidate_urls:
            if candidate_url != url:
                # Space the fallback the way rows are spaced: a row with a
                # fallback otherwise fires up to four requests back to back.
                # The delay is politeness towards the FCA and the Internet
                # Archive, so it belongs here too.
                time.sleep(PDFDownloader.INTER_REQUEST_DELAY_SECONDS)
                print(f"    Trying fallback source: {candidate_url}")
            for attempt in range(1, PDFDownloader.MAX_ATTEMPTS_PER_URL + 1):
                succeeded, reason = self._download_once(session, candidate_url,
                                                        destination)
                if succeeded:
                    return True, reason
                if first_reason == 'not attempted':
                    first_reason = reason
                if not self._is_transient_failure(reason):
                    break
                if attempt < PDFDownloader.MAX_ATTEMPTS_PER_URL:
                    print(f"    Attempt {attempt} failed ({reason}); "
                          f"retrying once after {PDFDownloader.RETRY_DELAY_SECONDS}s...")
                    time.sleep(PDFDownloader.RETRY_DELAY_SECONDS)
        return False, first_reason

    @staticmethod
    def _is_transient_failure(reason: str) -> bool:
        '''Only timeouts, connection problems and server-side 5xx responses
        deserve a second attempt. A 404 or an HTML landing page will answer
        identically next time — retrying just burns quota and build time.'''
        if reason.startswith('request error:'):
            return True
        return reason.startswith('HTTP 5')

    def _download_once(self, session: requests.Session, url: str,
                       destination: str) -> Tuple[bool, str]:
        '''Stream one URL to a temporary file and keep it only if it is a PDF.'''
        part_path = destination + '.part'
        oversized = False
        try:
            with session.get(url, stream=True,
                             timeout=PDFDownloader.REQUEST_TIMEOUT_SECONDS) as response:
                if response.status_code != 200:
                    return False, f"HTTP {response.status_code}"
                bytes_written = 0
                with open(part_path, 'wb') as part_file:
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            part_file.write(chunk)
                            bytes_written += len(chunk)
                            if bytes_written > PDFDownloader.MAX_DOWNLOAD_BYTES:
                                # Break rather than return: the part file is
                                # still open here, and discarding it must
                                # happen after the with block closes it.
                                oversized = True
                                break
        except requests_exceptions.RequestException as exc:
            self._discard_part(part_path)
            return False, f"request error: {exc}"

        if oversized:
            self._discard_part(part_path)
            return False, (f"response exceeds "
                           f"{PDFDownloader.MAX_DOWNLOAD_BYTES} byte limit")

        if not os.path.exists(part_path) or os.path.getsize(part_path) == 0:
            self._discard_part(part_path)
            return False, "empty response body"

        if not self._is_pdf_file(part_path):
            with open(part_path, 'rb') as part_file:
                head = part_file.read(16)
            self._discard_part(part_path)
            return False, f"not a PDF (body starts with {head!r})"

        os.replace(part_path, destination)
        return True, "downloaded"

    @staticmethod
    def _discard_part(part_path: str) -> None:
        if os.path.exists(part_path):
            os.remove(part_path)

    @staticmethod
    def _is_pdf_file(path: str) -> bool:
        '''A file counts as a PDF only if it is non-empty and %PDF- signed.'''
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            return False
        with open(path, 'rb') as candidate:
            return candidate.read(5) == b'%PDF-'


def display_summary(given, downloaded, skipped, failed):
    headers = ["Total", "Downloaded", "Skipped", "Fail"]
    data = [[given, downloaded, skipped, failed]]

    table = tabulate(data, headers=headers, tablefmt="pretty")
    print("-" * 26)
    print("Downloaded Documents")
    print(table)


def display_failures(failures: List[Tuple[str, str, str]]) -> None:
    if not failures:
        print("No failed downloads.")
        return
    print("Failed downloads:")
    for filename, link, reason in failures:
        print(f"  - {filename}")
        print(f"      {link}")
        print(f"      reason: {reason}")


def main():
    parser = argparse.ArgumentParser(
        description='Download the public source documents listed in '
                    'complyChat_sources.csv into app/documents/files/comply_sources.')
    parser.add_argument(
        '--force', action='store_true',
        help='Re-download even if a valid PDF is already present.')
    arguments = parser.parse_args()

    downloader = PDFDownloader()
    downloader.download_documents(force=arguments.force)


if __name__ == "__main__":
    main()
