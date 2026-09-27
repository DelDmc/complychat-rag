'''Rebuild the Chroma index in place, on a running machine.

The index lives on the machine's volume, at VECTOR_STORE_DIR (fly.toml), not
in the image. A deploy never touches it, so a change to the corpus, the
chunking or the embedding model reaches the app only through this script.
It also fills a new or replaced volume, which starts empty; until it does,
the app answers 503 rather than answer without sources.

In order:
  1. get the chunks: download the sources (the partial-corpus gate applies),
     load and split them, or read them from a file made by --export-chunks
  2. embed the chunks into a staging index, vector_store/chroma.new, in
     batches, which keeps memory flat on a 1GB machine that is also running
     two workers
  3. check the staging index: every chunk is in it, and a probe question
     retrieves documents the way the app does
  4. only then swap it in: remove vector_store/chroma and rename chroma.new
     into its place
  5. delete any downloaded PDFs, as the image build used to
  6. send SIGHUP to gunicorn, so fresh workers open the new index

Nothing touches the live index before step 4, so a run that fails or is
killed before then leaves it as it was, and a worker that restarts in the
meantime still opens a complete index. It also keeps the run's writes away
from the live path while the workers hold the old database open there:
SQLite can take a new database's journal at that path for a hot journal of
its own and roll it back. The next run clears any staging directory that a
failed run left behind.

Prepare the chunks locally and send the machine only the embedding. The
machine is poor at the rest: on 2026-09-25, fca.org.uk answered 403 to all
14 of its documents from there, and on shared-cpu-1x the text extraction
used up the CPU burst allowance and ran at about 7% of a core, so a full run
took about three hours against the builder's eight minutes. --export-chunks
downloads, loads and splits on this computer and needs no OpenAI key; the
machine embeds with its own. From the repository root, with the machine's
id from `fly machine list -a complychat`:

    (cd src && python reset_index.py --export-chunks /tmp/chunks.json.gz)
    fly machine update <id> -a complychat --autostop=off --yes
    fly ssh console -a complychat -C "rm -f /tmp/reset_index.py /tmp/chunks.json.gz"
    fly ssh sftp put src/reset_index.py /tmp/reset_index.py -a complychat
    fly ssh sftp put /tmp/chunks.json.gz /tmp/chunks.json.gz -a complychat
    fly ssh console -a complychat -C "sh -c 'cd /app && PYTHONPATH=/app setsid nohup python /tmp/reset_index.py --chunks /tmp/chunks.json.gz > /tmp/reset_index.log 2>&1 &'"
    fly ssh console -a complychat -C "tail -n 20 /tmp/reset_index.log"
    fly ssh console -a complychat -C "sh -c 'cd /app && PYTHONPATH=/app python /tmp/reset_index.py --check'"
    fly machine update <id> -a complychat --autostop=suspend --yes

Autostop is off for the run because a suspend can kill it. On 2026-09-27,
Fly began suspending the machine 11 minutes into a run, a request cancelled
the suspension, and the machine crashed and restarted with an empty /tmp.
The live index was untouched, and the next run cleared the half-built
staging index, but the run was lost. Requests to the public URL every
minute did not prevent the suspend. On 2026-09-25, requests every 30
seconds did not either, though that time the run paused and carried on.
Each machine update restarts the machine, which is harmless before the run
and after it.

Without --chunks it does everything on the machine, downloads included.

The script goes to /tmp, not /app: the image already has a copy at
/app/reset_index.py, and a machine that suspends keeps its own changes to
the root filesystem across deploys, so a file uploaded over the image's copy
would hide every later version of it.

--check reports on the current index and changes nothing.

With both workers up, available memory fell to about 45MB while embedding
the 8,959 chunks. `kill -TTOU <gunicorn master pid>` beforehand drops a worker, and
the final SIGHUP restores the configured two.
'''

import argparse
import gzip
import json
import os
import shutil
import signal
import sys
import time

import psutil
from langchain.docstore.document import Document

from app.documents import process_documents
from app.documents.document_splitter import DocumentSplitter
from app.documents.paths import APP_DOCS_DIR, CHROMA_DIR, VECTOR_STORE_DIR
from app.documents.pdf_loader import PDFLoader

# Built beside the live index, so the swap is a rename within one filesystem
# (the volume, on Fly), and inside vector_store/ so the ignore rules that keep
# a local index out of git and the build context cover it too.
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


def export_chunks(chunks, path):
    '''Write the chunks as gzipped JSON, for --chunks on the machine.'''
    records = [{'page_content': chunk.page_content,
                # The PDF's path on this computer; nothing reads it.
                'metadata': {**chunk.metadata,
                             'source': os.path.basename(chunk.metadata.get('source', ''))}}
               for chunk in chunks]
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        json.dump(records, f)


def load_chunks(path):
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        return [Document(**record) for record in json.load(f)]


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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check', action='store_true',
                      help='report on the current index and change nothing')
    mode.add_argument('--export-chunks', metavar='PATH',
                      help='download, load and split the corpus, write the chunks to PATH '
                           'and stop; needs no OpenAI key')
    mode.add_argument('--chunks', metavar='PATH',
                      help='index the chunks in PATH, written by --export-chunks, '
                           'instead of downloading the corpus')
    args = parser.parse_args()

    if args.export_chunks:
        chunks = build_chunks()
        if not chunks:
            sys.exit('No chunks to export.')
        export_chunks(chunks, args.export_chunks)
        print(f'Wrote {len(chunks)} chunks to {args.export_chunks}.', flush=True)
        return

    if not os.environ.get('OPENAI_API_KEY'):
        sys.exit('OPENAI_API_KEY is not set; it is needed to embed the corpus.')
    if args.check:
        from app.documents.vector_store import vectordb
        sys.exit(0 if check_index(vectordb) else 1)

    chunks = load_chunks(args.chunks) if args.chunks else build_chunks()
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
