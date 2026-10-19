from langchain_groq import ChatGroq
from dotenv import load_dotenv


load_dotenv()


llm = ChatGroq(
    model="openai/gpt-oss-20b"
)


def create_llm():
    return llm