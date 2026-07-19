from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from dotenv import load_dotenv
from config.llm_config import get_chat_llm
from utils.logger import logger

load_dotenv()
llm = get_chat_llm(temperature=0)

system = """
You are an AI assistant that converts natural language queries into SQL queries.
The table name is stock_data and the schema is:
id(integer), ticker(varchar), date(date), bar_ts(timestamptz), bar_interval(varchar: '1d' or '5m'),
open(double), high(double), low(double), close(double), volume(bigint).
Unique on (ticker, bar_ts, bar_interval). Prefer bar_interval='1d' for multi-day stats.
Convert the user question into a valid SQL query.
"""

sql_generation_prompt   = ChatPromptTemplate.from_messages(
    [
        ("system", system),
        ("human", "User question: {question}")
    ]
)
sql_generation_chain    = sql_generation_prompt | llm | StrOutputParser()

if __name__ == "__main__":
    question    = "Query the last 1 month of data for AAPL."

    res         = sql_generation_chain.invoke(input={
                "question": question,
    })

    logger.info(f"Generated SQL Query ={res}")
