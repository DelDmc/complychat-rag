from rest_framework import serializers


class MessageSerializer(serializers.Serializer):
    human = serializers.CharField(allow_blank=True)
    ai = serializers.CharField(allow_blank=True)
    
class ChatConfigSerializer(serializers.Serializer):
    full_prompt = serializers.CharField(max_length=10240)  # 2.5*4096 tokens assuming 1 token = 4-6 chars
    llm_model = serializers.CharField(max_length=64)
    llm_temperature = serializers.FloatField(min_value=0.0, max_value=1.0)
    
class ChatInputSerializer(serializers.Serializer):
    chat_history = MessageSerializer(many=True)
    question = serializers.CharField()
    config = ChatConfigSerializer()

    
    