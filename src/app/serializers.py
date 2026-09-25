from rest_framework import serializers

# Every character a caller sends reaches the model on the deployment's key.
# A question is a sentence or a paragraph; an answer from this chain is rarely
# more than a few thousand characters, and a client echoing back real answers
# should never meet the cap. Chat.get_answer also trims the history to a total
# budget, so these bound each message, not the whole conversation.
QUESTION_MAX_CHARS = 2000
ANSWER_MAX_CHARS = 8000


class MessageSerializer(serializers.Serializer):
    human = serializers.CharField(allow_blank=True, max_length=QUESTION_MAX_CHARS)
    ai = serializers.CharField(allow_blank=True, max_length=ANSWER_MAX_CHARS)

class ChatConfigSerializer(serializers.Serializer):
    # No llm_model and no full_prompt: both are fixed on the server
    # (Chat.llm_model, Chat.prompt_template), because the caller is anonymous
    # and the key is ours. A caller-supplied prompt made the endpoint a
    # general-purpose GPT-4 proxy, at up to 10KB of input per call. A client
    # that still sends either is not rejected; DRF drops undeclared fields, so
    # they have no effect.
    llm_temperature = serializers.FloatField(min_value=0.0, max_value=1.0)
    
class ChatInputSerializer(serializers.Serializer):
    chat_history = MessageSerializer(many=True)
    question = serializers.CharField(max_length=QUESTION_MAX_CHARS)
    config = ChatConfigSerializer()

    
    