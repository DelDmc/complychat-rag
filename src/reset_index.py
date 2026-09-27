'''Rebuild the Chroma index in place, on a running machine.

The Fly machine keeps its own filesystem changes across suspends and, as
release v4 showed, across deploys. A chroma.sqlite3 that an earlier release
had opened stayed on the machine and hid the populated one in the new image,
so the app read an empty collection and every answer came back with no
documents. Nothing failed and nothing was logged. This script replaces the
index on the machine itself.

In order:
  1. download the sources (the partial-corpus gate applies), load and split them
  2. embed the chunks into a staging index, vector_store/chroma.new, in
     batches, which keeps memory flat on a 1GB machine that is also running
     two workers
  3. check the staging index: every chunk is in it, and a probe question
     retrieves documents the way the app does
  4. only then swap it in: remove vector_store/chroma and rename chroma.new
     into its place
  5. delete the downloaded PDFs, as the image build does
  6. send SIGHUP to gunicorn, so fresh workers open the new index

Nothing touches the live index before step 4, so a run that fails or is
killed before then leaves it as it was, and a worker that restarts in the
meantime still opens a complete index. It also keeps the run's writes away
from the live path while the workers hold the old database open there:
SQLite can take a new database's journal at that path for a hot journal of
its own and roll it back. The next run clears any staging directory that a
failed run left behind. Step 4 removes chroma/ rather than renaming it
aside, because on an overlay root filesystem, renaming a directory that came
from the image can fail with EXDEV.

Fly may suspend the machine mid-run. It did once on 2026-09-25, even though
the app was being requested every 30 seconds. The process pauses and carries
on at the next request, so a run survives it.

Expect it to be slow and tight on memory. On shared-cpu-1x the text
extraction used up the CPU burst allowance and ran at about 7% of a core, so
the run took about three hours. The builder does the same step in about eight
minutes. With both workers up, available memory fell to about 45MB while
embedding the 8,959 chunks. `kill -TTOU <gunicorn master pid>` beforehand
drops a worker, and the final SIGHUP restores the configured two.

The rebuilt index lives in the machine's own filesystem, so it will outlast
the next deploy too. Run this again after changing the corpus, or recreate
the machine.

From the repository root. The script goes to /tmp, not /app: the image
already has a copy at /app/reset_index.py, and a file uploaded over it would
stay on the machine and hide the image's copy on every later deploy, the
same way chroma.sqlite3 did. The copy uploaded there on 2026-09-25 is
already such a file, so don't run /app/reset_index.py on that machine:

    fly ssh console -a complychat -C "rm -f /tmp/reset_index.py"
    fly ssh sftp put src/reset_index.py /tmp/reset_index.py -a complychat
    fly ssh console -a complychat -C "sh -c 'cd /app && PYTHONPATH=/app python /tmp/reset_index.py --check'"
    fly ssh console -a complychat -C "sh -c 'cd /app && PYTHONPATH=/app setsid nohup python /tmp/reset_index.py > /tmp/reset_index.log 2>&1 &'"
    fly ssh console -a complychat -C "tail -n 20 /tmp/reset_index.log"

--check reports on the current index and changes nothing.

Downloads from the machine can fail where the image build's succeed. On
2026-09-25, fca.org.uk answered 403 to all 14 of its documents and
legislation.gov.uk answered 202 to 3, and the partial-corpus gate stopped the
run before anything was wiped. Downloading locally and uploading the missing
files got past it, because PDFs already present and valid are skipped:

    cd src && python -c "from app.documents.process_documents import download_source_documents as d; d()"
    fly ssh sftp put src/app/documents/files/comply_sources/<file>.pdf \\
        /app/app/documents/files/comply_sources/<file>.pdf -a complychat
'''

import argparse
import os
import shutil
import signal
import sys
import time

import psutil

from app.documents import process_documents
from app.documents.document_splitter import DocumentSplitter
from app.documents.paths import APP_DOCS_DIR, CHROMA_DIR, VECTOR_STORE_DIR
from app.documents.pdf_loader import PDFLoader

# Built beside the live index, inside vector_store/ so the ignore rules that
# keep a local index out of git and the build context cover it too.
STAGING_DIR = VECTOR_STORE_DIR / 'chroma.new'

PROBE_QUESTION = 'What does the Consumer Duty require?'


def build_chunks():
    process_documents.download_source_documents(
        allow_partial=process_documents.allow_partial_from_env())
    documents = PDFLoader().load_documents()
    chunks = DocumentSplitter(documents=documents,
                              chunk_size=process_documents.CHUNK_SIZE,
                              chunk_overlap=process_documents.CHUNK_OVERLAP).split_documents()
    print(f'{len(documents)} documents split into {len(chunks)} chunks.', flush=True)
    return chunks


def build_staging_index(chunks):
    '''Embed the chunks into a fresh index at STAGING_DIR, and return it.'''
    # Imported here, not at the top: importing vector_store constructs the
    # embeddings client, which refuses to load without a key, and main()
    # checks for the key first so that a missing one gets a clear message.
    from app.documents.vector_store import EMBEDDING_BATCH_SIZE, open_vectordb
    shutil.rmtree(STAGING_DIR, ignore_errors=True)
    vectordb = open_vectordb(STAGING_DIR)
    # One embeddings request per batch.
    for start in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        vectordb.add_documents(chunks[start:start + EMBEDDING_BATCH_SIZE])
        print(f'Embedded {min(start + EMBEDDING_BATCH_SIZE, len(chunks))}/{len(chunks)} chunks.', flush=True)
    return vectordb


def swap_in_staging_index():
    '''Replace the live index with the checked staging index.'''
    if CHROMA_DIR.exists():
        shutil.rmtree(CHROMA_DIR)
    # chroma.new was created by this run, so renaming it is safe on an
    # overlay filesystem. shutil.move falls back to a copy if it is not.
    shutil.move(str(STAGING_DIR), str(CHROMA_DIR))
    print(f'Swapped the new index into {CHROMA_DIR}.', flush=True)


def check_index(vectordb, expected_count=None):
    '''Count the collection and retrieve for a probe question, as the app does.'''
    count = vectordb._collection.count()
    retriever = vectordb.as_retriever(search_type='mmr', search_kwargs={'k': 5, 'fetch_k': 50})
    docs = retriever.get_relevant_documents(PROBE_QUESTION)
    print(f'Index holds {count} chunks; "{PROBE_QUESTION}" retrieved {len(docs)} documents:', flush=True)
    for doc in docs:
        print(f'  - {doc.metadata.get("name")}', flush=True)
    if expected_count is not None and count != expected_count:
        print(f'Expected {expected_count} chunks.', flush=True)
        return False
    return count > 0 and len(docs) > 0


def is_gunicorn(cmdline):
    # "gunicorn ..." or "python .../gunicorn ...". Matching the whole command
    # line would also catch a shell whose command merely mentions gunicorn.
    return any(os.path.basename(arg) == 'gunicorn' for arg in (cmdline or [])[:2])


def gunicorn_master():
    '''The gunicorn process whose parent is not gunicorn, if there is exactly one.'''
    procs = [p for p in psutil.process_iter(['pid', 'ppid', 'cmdline'])
             if is_gunicorn(p.info['cmdline'])]
    pids = {p.info['pid'] for p in procs}
    masters = [p for p in procs if p.info['ppid'] not in pids]
    return masters[0] if len(masters) == 1 else None


def reload_workers():
    master = gunicorn_master()
    if master is None:
        print('Found no single gunicorn master; restart the app to load the new index.', flush=True)
        return False
    before = {child.pid for child in master.children()}
    master.send_signal(signal.SIGHUP)
    deadline = time.time() + 60
    while time.time() < deadline:
        time.sleep(2)
        now = {child.pid for child in master.children()}
        if now and not now & before:
            print(f'gunicorn replaced its workers {sorted(before)} with {sorted(now)}.', flush=True)
            return True
    print('gunicorn did not replace its workers within 60s; restart the app.', flush=True)
    return False


def main():
    parser = argparse.ArgumentParser(description='Rebuild the Chroma index on this machine.')
    parser.add_argument('--check', action='store_true',
                        help='report on the current index and change nothing')
    args = parser.parse_args()

    if not os.environ.get('OPENAI_API_KEY'):
        sys.exit('OPENAI_API_KEY is not set; it is needed to embed the corpus.')
    if args.check:
        from app.documents.vector_store import vectordb
        sys.exit(0 if check_index(vectordb) else 1)

    chunks = build_chunks()
    if not chunks:
        sys.exit('No chunks to index; the current index was left alone.')
    staged = build_staging_index(chunks)
    if not check_index(staged, expected_count=len(chunks)):
        shutil.rmtree(STAGING_DIR, ignore_errors=True)
        sys.exit('The new index failed its check; the live index and gunicorn were left alone.')
    swap_in_staging_index()
    # Reopened from the live path the way a worker will open it. Counting
    # reads SQLite only, so this does not load a second copy of the vectors.
    from app.documents.vector_store import open_vectordb
    live_count = open_vectordb()._collection.count()
    if live_count != len(chunks):
        sys.exit(f'The live index holds {live_count} chunks after the swap, not {len(chunks)}; '
                 'gunicorn was not reloaded.')
    shutil.rmtree(APP_DOCS_DIR, ignore_errors=True)
    if not reload_workers():
        sys.exit(1)
    print('Done: the app is serving the new index.', flush=True)


if __name__ == '__main__':
    main()
