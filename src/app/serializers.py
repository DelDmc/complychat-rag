from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    human = serializers.CharField(allow_blank=True)
    ai = serializers.CharField(allow_blank=True)
    
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
    question = serializers.CharField()
    config = ChatConfigSerializer()

    
    