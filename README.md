# ComplyChat

A document-grounded question-answering service over UK and EU financial regulation, where every answer carries links to the source documents it came from.

Compliance officers ask questions like *"what does the Consumer Duty require of a payments firm?"*. A plain LLM answer is useless to them, however fluent: an answer they cannot trace back to a named regulation cannot be acted on, and a confident answer citing the wrong regulation is worse than no answer. So ComplyChat retrieves from a fixed corpus of published regulation and returns the document name, relevance tags and live source link alongside every answer.

Built in 2023 as a prototype, and used by consultants at a regulatory-compliance consultancy in live client work. The code is mine outright — no NDA or IP claim — and the 2023 API keys were revoked before this repository existed.

## Status

**Runs locally. Not deployed.** There is no hosted demo yet. Deployment, and a minimal web page in front of the API, are the next pieces of work. Everything described below runs on a clean checkout.

## What it does

One POST endpoint, `POST /api/send-message/`. You send a question and the conversation so far; you get back an answer and the documents it was grounded in.

```json
{
  "question": "What does the Consumer Duty require?",
  "chat_history": [{"human": "...", "ai": "..."}],
  "config": {"full_prompt": "...", "llm_model": "gpt-4", "llm_temperature": 0.1}
}
```

The answer payload:

```json
{
  "answer": "...",
  "documents": [
    {"name": "A new Consumer Duty ... Policy Statement PS22-9",
     "relevance": "General Fin.Services,Payments/e-money",
     "link": "https://www.fca.org.uk/publication/policy/ps22-9.pdf"}
  ]
}
```

Follow-up questions work. The chain rewrites *"and what about crypto?"* into a standalone question before retrieval, using a custom condensing prompt in place of LangChain's default. Retrieval is only as good as the question it is given, so condensing is where a conversational RAG system quietly succeeds or fails.

The prompt, model and temperature are sent per request rather than baked in, so the wording could be retuned without a redeploy.

## The corpus

39 public documents, downloaded from their publishers' own URLs at build time. They are not vendored in this repository.

| Publisher | Documents |
| --- | --- |
| FCA — `fca.org.uk` policy statements and finalised guidance | 14 |
| FCA Handbook — `handbook.fca.org.uk` sourcebooks and chapters | 14 |
| `legislation.gov.uk` — UK Acts and statutory instruments | 6 |
| European Banking Authority — guidelines | 3 |
| JMLSG — anti-money-laundering guidance | 2 |

Mostly UK, but not only UK and not all FCA: the EBA guidelines are EU instruments that UK payment firms still work against. Each row in `complyChat_sources.csv` carries the citation metadata — `name`, `relevance`, `link` — that ends up attached to the answer.

## How it works

```
complyChat_sources.csv          39 rows: name, filename, relevance, link
         │
         ▼
  PDFDownloader                 fetch each public URL; keep the body only if it
         │                      starts with %PDF-; retry transient failures only;
         │                      fall back to archived copies where the live host
         │                      serves an app shell or a WAF challenge
         ▼
  PDFLoader (pdfminer.six)      extract text, and attach {name, relevance, link}
         │                      to each document inside the load loop
         ▼
  DocumentSplitter              RecursiveCharacterTextSplitter, 1500 chars, 100 overlap
         │
         ▼
  Chroma                        OpenAIEmbeddings, persisted to disk
         │
         ▼
  ConversationalRetrievalChain  retriever: MMR, k=5 selected from fetch_k=50
         │                      condenser: custom standalone-question prompt
         │                      temperature 0.1
         ▼
  POST /api/send-message/       answer + source documents
```

Three retrieval decisions worth naming:

- **MMR with `k=5, fetch_k=50`.** Plain similarity search tends to return five near-identical chunks of one sourcebook. Maximal marginal relevance picks five *diverse* chunks out of fifty candidates, which is what a question spanning several regulations needs.
- **Citation metadata is attached at ingestion, before embedding.** It travels with the chunk through the vector store, so retrieval cannot separate a chunk from the document it came from.
- **Temperature 0.1.** In a regulated domain, a varied answer is a defect.

## Tech stack

Python 3.10 · Django 4.1 · Django REST Framework · LangChain 0.0.300 (`ConversationalRetrievalChain`) · `openai` 0.27.8 · Chroma 0.4.3 · pdfminer.six · requests · gunicorn.

The LangChain and OpenAI pins are the 2023 versions the project was written against. Upgrading LangChain past 0.0.300 is a full rewrite of the chain, so the pins stay until that is a deliberate piece of work.

There are no Django models. The ORM is unused and the test suite needs no database.

## Running it locally

```bash
git clone https://github.com/DelDmc/complychat-rag.git
cd complychat-rag

python3.10 -m venv .venv
source .venv/bin/activate
pip install -r src/requirements.txt

cd src            # dotenv loads src/.env, and manage.py lives here
```

Create `src/.env`:

```
SECRET_KEY=<any random string for local use>
DJANGO_ALLOWED_HOSTS=127.0.0.1, localhost
OPENAI_API_KEY=<your key>
DEBUG=1
```

`DJANGO_ALLOWED_HOSTS` is required — settings splits it on `", "` exactly, and Django will not start without it. `OPENAI_API_KEY` is needed for embeddings and for the chat model. `DEBUG` defaults to off; set it to `1` for local development only.

Build the corpus and the index. This is the step that downloads the 39 PDFs and spends money on embeddings:

```bash
python -m app.documents.data_utils process_source_documents   # download, split, embed
```

Two other pipeline commands:

```bash
python -m app.documents.data_utils clear_vector_store         # wipe the index
python -m app.documents.data_utils reload_database            # wipe, then rebuild
```

The download step refuses to continue if any source document fails to fetch, so a partial index is never built by accident. To accept a short corpus deliberately, set `ALLOW_PARTIAL_CORPUS=1`; the shortfall is then logged at WARNING.

Run it:

```bash
python manage.py runserver                                    # development
gunicorn -c gunicorn_config.py config.wsgi:application        # as configured for deploy
```

## Testing

```bash
cd src
python manage.py test app
```

**27 tests, `unittest` through Django's test runner**, all `SimpleTestCase`. No network, no API key and no test database — HTTP is stubbed at the session boundary and the PDF loader is patched out. The suite covers the citation-metadata fix, the downloader's retry and fallback behaviour, the size cap, the skip-if-present path, the partial-corpus gate, and the sources CSV itself.

The citation tests were checked against the pre-fix loader as well as the fixed one. Drop the old `pdf_loader.py` into a throwaway copy of the tree and the same suite reports `FAILED (failures=2, errors=1)`, with the positional shift visible in the assertion — `'Consultation paper' != 'Unreadable guidance'`. A test that passes against both versions proves nothing.

## Engineering notes

**The citation bug.** The original loader attached citation metadata to documents by list position, *after* a loop that skips any PDF it cannot read. One unreadable file shifted every later citation by one — so an answer would name and link the wrong regulation, confidently and invisibly. In a compliance tool that is the worst failure available, because the output still looks perfect. The fix binds metadata inside the load loop, while the row describing the file is still in hand. Two regression tests hold it: one where a file in the middle fails to load, and one where a single PDF yields several documents and all of them must carry the same source.

**The same bug shape, in data.** Two rows of the sources CSV had their `name` column crossed against the correct `filename` and `link`. Not latent: both documents were already being cited under the wrong title. It is the same failure as the code bug — metadata and content drifting apart while the output still looks right. Fixed by swapping the names rather than the filenames, because the filenames are keys into the archived-fallback table and swapping those would have pointed each fallback at the wrong document. A test now locks the CSV: 39 rows, every row fetchable, every fallback key matching a real row.

**39 documents, not 43.** Four rows pointed at HTML landing pages with no fetchable PDF and no archived copy. Rather than carry four rows that would fail every build, they were dropped. Nothing substantive was lost — all four were secondary web pages rather than regulation, and the topics they covered are still in the corpus through the underlying policy statements. Shipping 39 that always work beat claiming 43 and failing on four.

**`DEBUG` defaulted to `True`.** Settings never read `DEBUG` from the environment; the line was commented out, and the remaining branch set `DEBUG = True` whenever a Heroku-specific variable was absent. On any non-Heroku host that means Django tracebacks and settings served to the public on any error, and setting `DEBUG=0` in the host's config would have been silently ignored. Caught in a pre-deployment review, before anything was ever exposed. **Fixed:** `DEBUG` is now read from the environment and defaults to off, so a host that forgets to set it fails safe rather than fails open.

**A trailing slash that costs 404s.** The plan is to move chat inference to Gemini's OpenAI-compatible endpoint, keeping OpenAI for embeddings. That was de-risked before committing to it, and the 2023 SDK does drive the endpoint — but only after stripping the trailing slash from the base URL. `openai==0.27.8` builds its URL by plain string concatenation, so the base URL exactly as documented produces `.../openai//chat/completions` and a 404. The client retries for about 30 seconds and surfaces `APIError: HTTP code 404 from API ()` with an empty message, which points at nothing. Worth writing down: the fix belongs in code as `.rstrip('/')`, not in a `.env` file, because the next person to copy the URL from the documentation will reintroduce it.

## What I would do differently

- **Retrieval evaluation.** There is none. A question set with known-correct source documents, scored on whether the right one is retrieved, is the first thing a serious team would ask for, and it is the honest gap here.
- **Structured logging instead of `print`.** Error handling still prints, and still returns the raw exception string to the client.
- **Tests from the start.** The suite was written years after the code. Writing the citation test first would have caught the position-matching bug before it ever shipped.

## Project layout

```
src/
├── manage.py
├── requirements.txt
├── gunicorn_config.py
├── config/                     Django project: settings, urls, wsgi
└── app/
    ├── views.py                POST /api/send-message/
    ├── serializers.py          request validation
    ├── retrieval_chain.py      ConversationalRetrievalChain, condenser, citations
    ├── tests.py                27 tests
    └── documents/              the ingestion pipeline
        ├── paths.py            all corpus paths, anchored to this module
        ├── csv_processor.py    reads complyChat_sources.csv
        ├── pdf_downloader.py   fetch, verify, retry, archived fallbacks
        ├── pdf_loader.py       extract text + attach citation metadata
        ├── document_splitter.py
        ├── vector_store.py     Chroma, persisted
        ├── process_documents.py  the pipeline and the partial-corpus gate
        └── files/              complyChat_sources.csv (the 39 rows)
```

## Contact

Kostiantyn Sokolov — [ksokolov.job@gmail.com](mailto:ksokolov.job@gmail.com)
