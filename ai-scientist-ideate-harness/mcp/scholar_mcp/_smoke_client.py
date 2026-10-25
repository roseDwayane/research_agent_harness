#!/usr/bin/env python3
"""Smoke test: start scholar_mcp over stdio the way Claude Code does, list its tools and run one small search
(Semantic Scholar + OpenAlex, 5 records each). Run it from this folder with the interpreter that has `mcp`."""

import asyncio
import json
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server = StdioServerParameters(command=sys.executable, args=["server.py"])
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("=== Tools exposed by scholar_mcp ===")
            for t in tools.tools:
                print(f"  - {t.name}")
            print()

            print("=== Calling scholar_search('predictive preventive brain-computer interface') ===")
            result = await session.call_tool(
                "scholar_search",
                {
                    "params": {
                        "query": "predictive preventive brain-computer interface",
                        "sources": ["semantic_scholar", "openalex"],
                        "limit": 5,
                        "year": "2019-2026",
                        "found_via": "Q1",
                    }
                },
            )
            text = result.content[0].text
            data = json.loads(text)

            print(f"sources_queried : {data['sources_queried']}")
            print(f"source_errors   : {data['source_errors']}")
            print(f"count           : {data['count']}")
            print()
            for i, p in enumerate(data["papers"], 1):
                title = (p["title"] or "")[:70]
                ab = (p["abstract"] or "")
                print(f"[{i}] {title}")
                print(f"    year={p['year']}  doi={p['doi']}  cites={p['citation_count']}")
                print(f"    sources={p['sources_found_in']}  found_via={p.get('found_via')}")
                print(f"    authors={p['authors'][:3]}")
                print(f"    abstract_len={len(ab)}  abstract[:90]={ab[:90]!r}")
                print()


if __name__ == "__main__":
    asyncio.run(main())
