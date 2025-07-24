from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from minitap.config import settings


def get_google_llm(
    model_name: str = "gemini-2.5-pro",
    temperature: float = 0.7,
) -> ChatGoogleGenerativeAI:
    client = ChatGoogleGenerativeAI(
        model=model_name,
        max_tokens=None,
        temperature=temperature,
        api_key=settings.GOOGLE_API_KEY,  # type: ignore[reportGeneralTypeIssues]
        max_retries=2,
    )
    return client


def get_openai_llm(
    model_name: str = "gpt-4o",  # gpt-4o-mini-2024-07-18
    temperature: float = 1,
) -> ChatOpenAI:
    client = ChatOpenAI(
        model=model_name,
        openai_api_key=settings.OPENAI_API_KEY,  # type: ignore[reportGeneralTypeIssues]
        temperature=temperature,
    )
    return client
