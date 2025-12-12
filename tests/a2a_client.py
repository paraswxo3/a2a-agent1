"""Extended from: https://github.com/a2aproject/a2a-samples/blob/main/samples/python/agents/langgraph/app/test_client.py"""

from dotenv import load_dotenv
load_dotenv()

import logging
from operator import truediv
from typing import Any
from uuid import uuid4
import httpx
from a2a.client import A2ACardResolver, A2AClient
from a2a.types import (
    AgentCard,
    MessageSendParams,
    SendMessageRequest,
    SendStreamingMessageRequest,
)
from a2a.utils.constants import (
    AGENT_CARD_WELL_KNOWN_PATH,
    EXTENDED_AGENT_CARD_PATH,
)

step_1 = True
step_2 = True
step_3 = True

async def main() -> None:
    print("=" * 60)
    print("Testing Currency Agent with Tool Calling with A2A")
    print("=" * 60)
    
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    # --8<-- [start:A2ACardResolver]
    logger.info("")
    logger.info("Step 0: Public Agent Card")
    logger.info("")

    base_url = 'http://localhost:10000'

    timeout = httpx.Timeout(120.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as httpx_client:
        resolver = A2ACardResolver(
            httpx_client=httpx_client,
            base_url=base_url,
        )
        # --8<-- [end:A2ACardResolver]

        final_agent_card_to_use: AgentCard | None = None
        try:
            logger.info(
                f'Attempting to fetch public agent card from: {base_url}{AGENT_CARD_WELL_KNOWN_PATH}'
            )
            _public_card = (
                await resolver.get_agent_card()
            )
            logger.info('Successfully fetched public agent card:')
            logger.info(
                _public_card.model_dump_json(indent=2, exclude_none=True)
            )
            final_agent_card_to_use = _public_card
            logger.info(
                '\nUsing PUBLIC agent card for client initialization (default).'
            )
            if _public_card.supports_authenticated_extended_card:
                try:
                    logger.info(
                        '\nPublic card supports authenticated extended card. '
                        'Attempting to fetch from: '
                        f'{base_url}{EXTENDED_AGENT_CARD_PATH}'
                    )
                    auth_headers_dict = {
                        'Authorization': 'Bearer dummy-token-for-extended-card'
                    }
                    _extended_card = await resolver.get_agent_card(
                        relative_card_path=EXTENDED_AGENT_CARD_PATH,
                        http_kwargs={'headers': auth_headers_dict},
                    )
                    logger.info(
                        'Successfully fetched authenticated extended agent card:'
                    )
                    logger.info(
                        _extended_card.model_dump_json(
                            indent=2, exclude_none=True
                        )
                    )
                    final_agent_card_to_use = (
                        _extended_card
                    )
                    logger.info(
                        '\nUsing AUTHENTICATED EXTENDED agent card for client '
                        'initialization.'
                    )
                except Exception as e_extended:
                    logger.warning(
                        f'Failed to fetch extended agent card: {e_extended}. '
                        'Will proceed with public card.',
                        exc_info=True,
                    )
            elif (
                _public_card
            ):
                logger.info(
                    '\nPublic card does not indicate support for an extended card. Using public card.'
                )
        except Exception as e:
            logger.error(
                f'Critical error fetching public agent card: {e}', exc_info=True
            )
            raise RuntimeError(
                'Failed to fetch the public agent card. Cannot continue.'
            ) from e

        send_message_payload: dict[str, Any] = {
            'message': {
                'role': 'user',
                'parts': [
                    {'kind': 'text', 'text': 'How much is 1 USD in EUR?'}
                ],
                'message_id': uuid4().hex,
            },
        }

        client = A2AClient(
            httpx_client=httpx_client,
            agent_card=final_agent_card_to_use
        )
        logger.info('A2AClient initialized')

        # --8<-- [start:send_message]
        if step_1:
            logger.info("")
            logger.info("Step 1: Send Message Synch")
            logger.info("")

            request = SendMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )
            response = await client.send_message(request)
            response_dict = response.model_dump(mode='json', exclude_none=True)
            print(response_dict)
            
            if 'error' in response_dict:
                logger.error(f"Error in first send_message response: {response_dict['error']}")
                raise RuntimeError(f"Server returned error: {response_dict['error'].get('message', 'Unknown error')}")
        # --8<-- [end:send_message]

        # --8<-- [start:send_message_streaming]
        if step_2:
            logger.info("")
            logger.info("Step 2: Send Message Streaming")
            logger.info("")

            streaming_request = SendStreamingMessageRequest(
                id=str(uuid4()), params=MessageSendParams(**send_message_payload)
            )
            stream_response = client.send_message_streaming(streaming_request)

            async for chunk in stream_response:
                print(chunk.model_dump(mode='json', exclude_none=True))
        # --8<-- [end:send_message_streaming]

        # --8<-- [start:Multiturn]
        if step_3:
            logger.info("")
            logger.info("Step 3: Send Messages Multiturn")
            logger.info("")

            send_message_payload_multiturn: dict[str, Any] = {
                'message': {
                    'role': 'user',
                    'parts': [
                        {
                            'kind': 'text',
                            'text': 'How much is the exchange rate for 1 USD?',
                        }
                    ],
                    'message_id': uuid4().hex,
                },
            }
            request = SendMessageRequest(
                id=str(uuid4()),
                params=MessageSendParams(**send_message_payload_multiturn),
            )

            response = await client.send_message(request)
            print(response.model_dump(mode='json', exclude_none=True))

            response_dict = response.model_dump(mode='json', exclude_none=True)
            if 'error' in response_dict:
                logger.error(f"Error in multiturn send_message response: {response_dict['error']}")
                raise RuntimeError(f"Server returned error: {response_dict['error'].get('message', 'Unknown error')}")
            
            result = response_dict.get('result', {})
            task_id = result.get('id')
            context_id = result.get('contextId')
            
            if not task_id or not context_id:
                logger.error(f"Missing task_id or context_id in response: {response_dict}")
                raise RuntimeError("Server response missing required fields")

            second_send_message_payload_multiturn: dict[str, Any] = {
                'message': {
                    'role': 'user',
                    'parts': [{'kind': 'text', 'text': 'EUR'}],
                    'message_id': uuid4().hex,
                    'task_id': task_id,
                },
                'context_id': context_id,
            }

            second_request = SendMessageRequest(
                id=str(uuid4()),
                params=MessageSendParams(**second_send_message_payload_multiturn),
            )

            second_response = await client.send_message(second_request)
            print(second_response.model_dump(mode='json', exclude_none=True))
        # --8<-- [end:Multiturn]

if __name__ == '__main__':
    import asyncio
    asyncio.run(main())