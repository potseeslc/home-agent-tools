"""Opt-in live protocol check: never prints bearer tokens or service results.

HAT_MCP_URL=http://localhost:4444/mcp HAT_TOKEN_FILE=/private/token python tests/smoke_mcp.py
Use an enrolled read-only test agent. Revoke it when finished.
"""
import asyncio
import os
from pathlib import Path

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main():
    token = Path(os.environ['HAT_TOKEN_FILE']).read_text().strip()
    headers = {'Authorization': 'Bearer ' + token}
    if os.environ.get('HAT_TEST_HOST'):
        headers['Host'] = os.environ['HAT_TEST_HOST']
    async with httpx2.AsyncClient(headers=headers) as client:
        async with streamable_http_client(os.environ['HAT_MCP_URL'], http_client=client) as streams:
            async with ClientSession(*streams) as session:
                init = await session.initialize()
                listed = await session.list_tools()
                names = {tool.name for tool in listed.tools}
                assert 'ha-api-status' in names
                result = await session.call_tool('ha-api-status', {})
                assert not result.is_error
                print('SDK initialize/discovery/read passed:', init.protocol_version, len(names), 'tools')


if __name__ == '__main__':
    asyncio.run(main())
