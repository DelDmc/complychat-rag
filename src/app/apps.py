from django.apps import AppConfig
from app.documents.vector_store import vectordb
from app.retrieval_chain import Chat


class AppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
    chat = None
    # Chunks in the index when this worker started. The endpoint refuses to
    # answer from an empty index, which is what a new or replaced volume
    # holds until reset_index.py fills it.
    index_size = 0

    def ready(self):
        AppConfig.chat = Chat()
        AppConfig.chat.create_chain()
        AppConfig.index_size = vectordb._collection.count()
            
