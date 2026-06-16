#!/usr/bin/env python
"""
Quick test script for v2.1 experimental endpoint.

Usage:
    python test_v21_endpoint.py

Requires the API server to be running on http://localhost:8000
"""

import asyncio

import httpx


async def test_experimental_endpoint():
    """Test the /query/experimental endpoint."""
    
    queries = [
        "What are the best offlane heroes?",
        "Give me carry recommendations",
        "Which mid heroes should I play?",
        "Best support heroes right now",
    ]
    
    async with httpx.AsyncClient(base_url="http://localhost:8000") as client:
        for query in queries:
            print(f"\n{'='*60}")
            print(f"Query: {query}")
            print('='*60)
            
            try:
                response = await client.post(
                    "/api/v1/query/experimental",
                    json={"query": query, "game": "dota2"},
                    timeout=30.0,
                )
                response.raise_for_status()
                
                data = response.json()
                
                print(f"✅ Routed to: {data['routed_service']}")
                print(f"📋 Analysis steps: {len(data['tasks'])}")
                for task in data['tasks']:
                    print(f"   - {task['action']}")
                
                result = data['result']
                print(f"\n📊 Report:")
                print(f"   Role: {result['role']}")
                print(f"   Patch: {result['patch']}")
                print(f"   Confidence: {result['confidence']:.2%}")
                print(f"   Top heroes: {len(result['top_heroes'])}")
                
                if result['top_heroes']:
                    print(f"\n🏆 Top 3 heroes:")
                    for i, hero in enumerate(result['top_heroes'][:3], 1):
                        print(f"   {i}. {hero['hero']}")
                        print(f"      Meta Score: {hero['meta_score']}/100")
                        print(f"      Win Rate: {hero['win_rate']:.1%}")
                        print(f"      Confidence: {hero['confidence']:.1%}")
                        print(f"      Evidence: {len(hero['evidence'])} items")
                        
            except httpx.HTTPError as e:
                print(f"❌ Request failed: {e}")
            except Exception as e:
                print(f"❌ Error: {e}")


def main():
    print("=" * 60)
    print("v2.1 Experimental Endpoint Test")
    print("=" * 60)
    print("\nMake sure the API server is running:")
    print("  cd apps/api && uvicorn app.main:app --reload")
    print()
    
    asyncio.run(test_experimental_endpoint())
    
    print("\n" + "=" * 60)
    print("Test completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
