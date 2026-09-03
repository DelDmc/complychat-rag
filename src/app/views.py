from django.http import JsonResponse
from django.shortcuts import render
from rest_framework.decorators import api_view, parser_classes
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework import status

from app.apps import AppConfig
from app.serializers import ChatInputSerializer


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
    if request.method == 'POST':
        serializer = ChatInputSerializer(data=request.data)

        if serializer.is_valid():
            # Valid data, you can access it using serializer.validated_data
            chat_history = serializer.validated_data['chat_history']
            question = serializer.validated_data['question']
            processed_chat_history = [(message.get("human", ""), message.get("ai", "")) for message in chat_history if message["ai"]]
            config = serializer.validated_data['config']
            
        # Request data is correct now pass it to LLM
        try:
            chat = AppConfig.chat
            chat.prompt_template = config['full_prompt']
            chat.llm_model = config['llm_model']
            chat.llm_temperature = config['llm_temperature']
            response = chat.get_answer(question, processed_chat_history)
            return Response(response, status=status.HTTP_200_OK)

        except Exception as e:
            # Log the error or print it for debugging purposes
            print(f"Error in send_message: {e}")

            # Return an error response to the client
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)