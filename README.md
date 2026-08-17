## ComplyChat

### Clear vector store only
``python -m app.documents.data_utils clear_vector_store``

### Process pdf loading, splitting, embedding and creating Chroma db
``python -m app.documents.data_utils process_source_documents``

### Combines prevoius two commands, clears and reloads DB
``python -m app.documents.data_utils reload_database``

### Start the application
``gunicorn -c gunicorn_config.py config.wsgi:application``