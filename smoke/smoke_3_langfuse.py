from dotenv import load_dotenv
from langfuse import get_client
from langfuse.langchain import CallbackHandler
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

load_dotenv()
langfuse = get_client()
print("auth:", langfuse.auth_check())

chain = ChatPromptTemplate.from_messages([("user", "Di solo: {palabra}")]) | ChatOpenAI(model="gpt-4o", temperature=0)
handler = CallbackHandler()

with langfuse.start_as_current_observation(as_type="span", name="smoke-root") as root:
    with langfuse.start_as_current_observation(as_type="span", name="hijo-1"):
        chain.invoke({"palabra": "hola"}, config={"callbacks": [handler]})

langfuse.flush()
print("listo, revisá el dashboard")