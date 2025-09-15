import sys
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import BaseModel

sys.modules["langgraph.prebuilt.chat_agent_executor"] = Mock()
sys.modules["minitap.mobile_use.graph.state"] = Mock()
sys.modules["langchain_google_vertexai"] = Mock()
sys.modules["langchain_google_genai"] = Mock()
sys.modules["langchain_openai"] = Mock()
sys.modules["langchain_cerebras"] = Mock()

from minitap.mobile_use.agents.outputter.outputter import outputter  # noqa: E402
from minitap.mobile_use.config import LLM, OutputConfig  # noqa: E402
from minitap.mobile_use.context import MobileUseContext  # noqa: E402
from minitap.mobile_use.utils.logger import get_logger  # noqa: E402

logger = get_logger(__name__)


class MockPydanticSchema(BaseModel):
    color: str
    price: float
    currency_symbol: str
    website_url: str


mock_dict = {
    "color": "green",
    "price": 20,
    "currency_symbol": "$",
    "website_url": "http://superwebsite.fr",
}


class DummyState:
    def __init__(self, messages, initial_goal, agents_thoughts):
        self.messages = messages
        self.initial_goal = initial_goal
        self.agents_thoughts = agents_thoughts


mocked_state = DummyState(
    messages=[],
    initial_goal="Find a green product on my website",
    agents_thoughts=[
        "Going on http://superwebsite.fr",
        "Searching for products",
        "Filtering by color",
        "Color 'green' found for a 20 dollars product",
    ],
)


@pytest.fixture
def mock_context():
    """Create a properly mocked context with all required fields."""
    ctx = Mock(spec=MobileUseContext)
    ctx.llm_config = {
        "executor": LLM(provider="openai", model="gpt-5-nano"),
        "cortex": LLM(provider="openai", model="gpt-5-nano"),
        "planner": LLM(provider="openai", model="gpt-5-nano"),
        "orchestrator": LLM(provider="openai", model="gpt-5-nano"),
    }
    ctx.device = Mock()
    ctx.hw_bridge_client = Mock()
    ctx.screen_api_client = Mock()
    return ctx


@pytest.fixture
def mock_state():
    """Create a mock state with test data."""
    return DummyState(
        messages=[],
        initial_goal="Find a green product on my website",
        agents_thoughts=[
            "Going on http://superwebsite.fr",
            "Searching for products",
            "Filtering by color",
            "Color 'green' found for a 20 dollars product",
        ],
    )


@patch("minitap.mobile_use.agents.outputter.outputter.get_llm")
@pytest.mark.asyncio
async def test_outputter_with_pydantic_model(mock_get_llm, mock_context, mock_state):
    """Test outputter with Pydantic model output."""
    # Mock the structured LLM response
    mock_structured_llm = AsyncMock()
    mock_structured_llm.ainvoke.return_value = MockPydanticSchema(
        color="green", price=20, currency_symbol="$", website_url="http://superwebsite.fr"
    )

    # Mock the base LLM
    mock_llm = Mock()
    mock_llm.with_structured_output.return_value = mock_structured_llm
    mock_get_llm.return_value = mock_llm

    config = OutputConfig(
        structured_output=MockPydanticSchema,
        output_description=None,
    )

    result = await outputter(ctx=mock_context, output_config=config, graph_output=mock_state)

    assert isinstance(result, dict)
    assert result.get("color") == "green"


@patch("minitap.mobile_use.agents.outputter.outputter.get_llm")
@pytest.mark.asyncio
async def test_outputter_with_dict(mock_get_llm, mock_context, mock_state):
    """Test outputter with dictionary output."""
    # Mock the structured LLM response for dict
    mock_structured_llm = AsyncMock()
    expected_dict = {
        "color": "green",
        "price": 20,
        "currency_symbol": "$",
        "website_url": "http://superwebsite.fr",
    }
    mock_structured_llm.ainvoke.return_value = expected_dict

    # Mock the base LLM
    mock_llm = Mock()
    mock_llm.with_structured_output.return_value = mock_structured_llm
    mock_get_llm.return_value = mock_llm

    config = OutputConfig(
        structured_output=mock_dict,
        output_description=None,
    )

    result = await outputter(ctx=mock_context, output_config=config, graph_output=mock_state)

    assert isinstance(result, dict)
    assert result.get("color") == "green"
    assert result.get("price") == 20
    assert result.get("currency_symbol") == "$"
    assert result.get("website_url") == "http://superwebsite.fr"


@patch("minitap.mobile_use.agents.outputter.outputter.get_llm")
@pytest.mark.asyncio
async def test_outputter_with_natural_language_output(mock_get_llm, mock_context, mock_state):
    """Test outputter with natural language description output."""
    # Mock the LLM response for natural language output (no structured output)
    mock_llm = AsyncMock()
    expected_json = '{"color": "green", "price": 20, "currency_symbol": "$", "website_url": "http://superwebsite.fr"}'
    mock_llm.ainvoke.return_value = Mock(content=expected_json)
    mock_get_llm.return_value = mock_llm

    config = OutputConfig(
        structured_output=None,
        output_description=(
            "A JSON object with a color, a price, a currency_symbol and a website_url key"
        ),
    )

    result = await outputter(ctx=mock_context, output_config=config, graph_output=mock_state)

    assert isinstance(result, dict)
    assert result.get("color") == "green"
    assert result.get("price") == 20
    assert result.get("currency_symbol") == "$"
    assert result.get("website_url") == "http://superwebsite.fr"
