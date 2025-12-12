import os
from collections.abc import AsyncIterable
from typing import Any, Literal
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent
from langchain_ibm import ChatWatsonx
from pydantic import BaseModel, SecretStr
from .tools import get_exchange_rate
from .tracer import (
    trace_stream_start,
    trace_stream_end,
    trace_iteration,
)

memory = MemorySaver()

class ResponseFormat(BaseModel):
    """Respond to the user in this format."""

    status: Literal['input_required', 'completed', 'error'] = 'input_required'
    message: str

class CurrencyAgent:
    SYSTEM_INSTRUCTION = (
        'You are a specialized assistant for currency conversions. '
        "Your sole purpose is to use the 'get_exchange_rate' tool to answer questions about currency exchange rates. "
        'If the user asks about anything other than currency conversion or exchange rates, '
        'politely state that you cannot help with that topic and can only assist with currency-related queries. '
        'Do not attempt to answer unrelated questions or use tools for other purposes. '
        'You must not assume the currencies. Instead ask user for clarification. '
        'Remember: You must invoke the tool to convert the currency!'
    )

    FORMAT_INSTRUCTION = (
        'Set response status to input_required if the user needs to provide more information to complete the request.'
        'Set response status to error if there is an error while processing the request.'
        'Set response status to completed if the request is complete.'
    )

    def __init__(self):
        watsonx_url = os.getenv("WATSONX_URL", "https://us-south.ml.cloud.ibm.com")
        watsonx_apikey = os.getenv("WATSONX_API_KEY", "")
        
        self.model = ChatWatsonx(
            model_id=os.getenv("WATSONX_MODEL_ID", "openai/gpt-oss-120b"),
            url=SecretStr(watsonx_url),
            apikey=SecretStr(watsonx_apikey),
            project_id=os.getenv("WATSONX_PROJECT_ID"),
            params={
                "max_new_tokens": int(os.getenv("WATSONX_MAX_NEW_TOKENS", "1024")),
                "temperature": float(os.getenv("WATSONX_TEMPERATURE", "0.0")),
                "top_p": float(os.getenv("WATSONX_TOP_P", "1.0")),
                "top_k": int(os.getenv("WATSONX_TOP_K", "50")),
            }
        )
        
        self.tools = [get_exchange_rate]
        self.graph = create_react_agent(
            self.model,
            tools=self.tools,
            checkpointer=memory,
            prompt=self.SYSTEM_INSTRUCTION,
            response_format=(self.FORMAT_INSTRUCTION, ResponseFormat),
        )

    async def stream(self, query, context_id) -> AsyncIterable[dict[str, Any]]:
        trace_stream_start(context_id, query)
        inputs = {'messages': [('user', query)]}
        config: RunnableConfig = {'configurable': {'thread_id': context_id}}  # type: ignore

        async for item in self.graph.astream(inputs, config, stream_mode='values'):
            if 'messages' not in item or not item['messages']:
                continue    
            message = item['messages'][-1]
            if (
                isinstance(message, AIMessage)
                and message.tool_calls
                and len(message.tool_calls) > 0
            ):
                trace_iteration('AIMessage', has_tool_calls=True)
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Looking up the exchange rates ... ',
                }
            elif isinstance(message, ToolMessage):
                trace_iteration('ToolMessage')
                yield {
                    'is_task_complete': False,
                    'require_user_input': False,
                    'content': 'Processing the exchange rates ... ',
                }
        trace_iteration('AIMessage (final) MODIFIED.....')
        trace_stream_end()
        
        yield self.get_agent_response(config)

    def get_agent_response(self, config) -> dict[str, Any]:
        try:
            current_state = self.graph.get_state(config)
            structured_response = current_state.values.get('structured_response')
            # --- START FIX: MANUALLY EXTRACT FINAL MESSAGE AND CONSTRUCT RESPONSE ---
            # If structured_response is None, try to get the final message content
            if structured_response is None:
                # Get the last message in the conversation history
                final_message = current_state.values['messages'][-1]
                print("final message ",final_message)
                if isinstance(final_message, AIMessage):
                    # Use the content of the final AIMessage to create the completed response
                    structured_response = ResponseFormat(
                        status='completed',
                        message=final_message.content
                    )
                    # For debugging, log the message we used
                    from .tracer import Tracer
                    Tracer.trace('debug_fix', 'BUILT_STRUCTURED_RESPONSE',
                                message_content=structured_response.message[:100] + '...',
                                status=structured_response.status)
                
            # --- END FIX ---
            if structured_response and isinstance(
                structured_response, ResponseFormat
            ):
                if structured_response.status == 'input_required':
                    return {
                        'is_task_complete': False,
                        'require_user_input': True,
                        'content': structured_response.message,
                    }
                if structured_response.status == 'error':
                    return {
                        'is_task_complete': False,
                        'require_user_input': True,
                        'content': structured_response.message,
                    }
                if structured_response.status == 'completed':
                    return {
                        'is_task_complete': True,
                        'require_user_input': False,
                        'content': structured_response.message,
                    }
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': (
                    'Unable to determine response status. '
                    'Please try again or provide more information.'
                ),
            }
            
        except Exception as e:
            print(f"Error in get_agent_response: {e}")
            return {
                'is_task_complete': False,
                'require_user_input': True,
                'content': (
                    'We are unable to process your request at the moment. '
                    'Please try again.'
                ),
            }

    SUPPORTED_CONTENT_TYPES = ['text', 'text/plain']