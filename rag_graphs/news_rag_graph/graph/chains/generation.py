from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from config.llm_config import get_chat_llm

load_dotenv()

llm = get_chat_llm(temperature=0)

rag_prompt = ChatPromptTemplate.from_messages([
    ("system", "You are an assistant for question-answering tasks. Use the following pieces of retrieved context to answer the question. If you don't know the answer, say that you don't know. Use three sentences maximum and keep the answer concise."),
    ("human", "Context:\n{context}\n\nQuestion: {question}"),
])

generation_chain = rag_prompt | llm | StrOutputParser()
