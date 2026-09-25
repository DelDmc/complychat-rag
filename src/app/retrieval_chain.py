from dotenv import load_dotenv
from langchain import LLMChain, PromptTemplate
from langchain.chains import ConversationalRetrievalChain
from langchain.chat_models import ChatOpenAI
from app.documents.vector_store import vectordb

load_dotenv()

# The condensing call sees the chat history, and the caller writes all of it,
# the `ai` turns included. Ten maximum-length turns would fill the model's
# context window on every call. Only the most recent turns that fit in this
# budget are kept, about 3k tokens; a follow-up rarely needs more than the
# last exchange or two. It is larger than one maximum-length pair
# (serializers.QUESTION_MAX_CHARS + ANSWER_MAX_CHARS), so the newest turn
# always survives.
HISTORY_MAX_PAIRS = 10
HISTORY_MAX_CHARS = 12000


def recent_history(chat_history, max_pairs=HISTORY_MAX_PAIRS, max_chars=HISTORY_MAX_CHARS):
    '''The most recent (human, ai) pairs that fit in max_chars, oldest first.'''
    kept = []
    total = 0
    for human, ai in reversed(chat_history[-max_pairs:]):
        total += len(human) + len(ai)
        if total > max_chars:
            break
        kept.append((human, ai))
    return kept[::-1]


class Chat:
    prompt_template: str = "Given the following chat_history and a follow up question, summirize the chat_history and combine with the follow up question to be a standalone question, in its original language. NEVER EVER say that as AI you don't have the ability to recall previous discussions. \n\nChat History:\n{chat_history}\nFollow Up Input: {question}\nStandalone question:"
    llm_model: str = 'gpt-4'
    llm_temperature: float = 0.1
    # "gpt-3.5-turbo-0613"
    def create_chain(self):
        retriever = vectordb.as_retriever(search_type="mmr", search_kwargs={'k': 5, 'fetch_k': 50})
        qa = ConversationalRetrievalChain.from_llm(
            llm=ChatOpenAI(model_name='gpt-4', temperature=0.1),
            chain_type="stuff",
            retriever=retriever,
            return_source_documents=True,
            return_generated_question=True,
        )
        return qa

    def get_answer(self, question, chat_history):
        chain = self.create_chain()
        prompt = PromptTemplate.from_template(self.prompt_template)
        question_generator = LLMChain(prompt=prompt, llm=ChatOpenAI(model_name=self.llm_model, temperature=self.llm_temperature))
        
        chain.question_generator = question_generator
        chat_history = recent_history(chat_history)
        
        result = chain({"question":question, "chat_history": chat_history})

        sources = extract_sources(result["source_documents"])
        return {'answer':result['answer'], 'documents':sources}

def extract_sources(docs):
    sources = []
    for idx,document in enumerate(docs, 1):
        sources.extend([{'name':document.metadata['name'],'relevance':document.metadata['relevance'],'link': document.metadata['link']}])
    return sources