from dotenv import load_dotenv
load_dotenv()

# from app.langgraph_agent import CurrencyAgent
import asyncio
from app.langgraph_agent import CurrencyAgent

async def test_currency_conversion():
    print("=" * 60)
    print("Testing Currency Agent with Tool Calling without A2A")
    print("=" * 60)
    
    agent: CurrencyAgent = CurrencyAgent()
    
    query = "How much is 1 USD in EUR?"
    context_id = "test_context_1234"
    
    print(f"\nQuery: {query}")
    print("-" * 60)
    
    async for item in agent.stream(query, context_id):
        print(f"\nAgent Response Stream - Status:")
        print("-" * 60)
        print(f"  - Task Complete: {item['is_task_complete']}")
        print(f"  - Requires Input: {item['require_user_input']}")
        print(f"  - Content: {item['content']}")
        print("-" * 60)

if __name__ == "__main__":
    asyncio.run(test_currency_conversion())