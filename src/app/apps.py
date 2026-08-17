from django.apps import AppConfig
from app.retrieval_chain import Chat


class AppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "app"
    chat = None

    def ready(self):
        AppConfig.chat = Chat()
        AppConfig.chat.create_chain()
            
