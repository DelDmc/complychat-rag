import logging

from django.http import JsonResponse
from django.shortcuts import render
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status

from app.apps import AppConfig
from app.serializers import ChatInputSerializer

logger = logging.getLogger(__name__)

GENERIC_ERROR = 'The answer could not be generated. Please try again later.'


def index(request):
    """The landing page. Currently a placeholder; the chat UI replaces it."""
    return render(request, 'index.html')


def healthz(request):
    """Liveness probe for the platform's health check.

    Deliberately touches neither the chain nor the vector store: this must
    answer while the corpus is missing or the LLM is rate-limited, or the
    platform will kill a process that is merely degraded.
    """
    return JsonResponse({'status': 'ok'})


@api_view(['POST'])
@parser_classes([JSONParser])
def send_message(request):
    serializer = ChatInputSerializer(data=request.data)
    if not serializer.is_valid():
        # The client's own input, described back to it: safe to return.
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    chat_history = serializer.validated_data['chat_history']
    question = serializer.validated_data['question']
    processed_chat_history = [(message.get("human", ""), message.get("ai", "")) for message in chat_history if message["ai"]]
    config = serializer.validated_data['config']

    try:
        chat = AppConfig.chat
        chat.llm_temperature = config['llm_temperature']
        response = chat.get_answer(question, processed_chat_history)
        return Response(response, status=status.HTTP_200_OK)

    except Exception:
        # The exception text stays in the server log. Upstream errors are not
        # safe to hand to a public caller: OpenAI's authentication error quotes
        # the first few and last four characters of the API key it rejected.
        logger.exception("send_message failed")
        return Response({'error': GENERIC_ERROR}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
