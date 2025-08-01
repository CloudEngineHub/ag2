# Copyright (c) 2023 - 2025, AG2ai, Inc., AG2ai open-source projects maintainers and core contributors
#
# SPDX-License-Identifier: Apache-2.0

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import anyio
import pytest
from pydantic.networks import AnyUrl

from autogen import AssistantAgent
from autogen.import_utils import optional_import_block, run_for_optional_imports, skip_on_missing_imports
from autogen.mcp.mcp_client import ResultSaved, create_toolkit

from ..conftest import Credentials

with optional_import_block():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import ReadResourceResult, TextResourceContents


@skip_on_missing_imports(
    [
        "mcp.client.stdio",
        "mcp.server.fastmcp",
    ],
    "mcp",
)
class TestMCPClient:
    @pytest.fixture
    def server_params(self) -> "StdioServerParameters":  # type: ignore[no-any-unimported]
        server_file = Path(__file__).parent / "math_server.py"
        return StdioServerParameters(
            command="python3",
            args=[str(server_file)],
        )

    @pytest.mark.asyncio
    async def test_mcp_issue_with_stdio_client_context_manager(self, server_params: "StdioServerParameters") -> None:  # type: ignore[no-any-unimported]
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as _:
                pass
            print("exit ClientSession")
        print("exit stdio_client")

    @pytest.mark.asyncio
    async def test_tools_schema(self, server_params: "StdioServerParameters", mock_credentials: Credentials) -> None:  # type: ignore[no-any-unimported]
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            # Initialize the connection
            await session.initialize()
            toolkit = await create_toolkit(session=session)
            assert len(toolkit) == 3

            agent = AssistantAgent(
                name="agent",
                llm_config=mock_credentials.llm_config,
            )
            toolkit.register_for_llm(agent)
            expected_schema = [
                {
                    "type": "function",
                    "function": {
                        "name": "add",
                        "description": "Add two numbers",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "arguments": {
                                    "type": "object",
                                    "description": "arguments",
                                    "additionalProperties": True,
                                }
                            },
                            "required": ["arguments"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "name": "multiply",
                        "description": "Multiply two numbers",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "arguments": {
                                    "type": "object",
                                    "description": "arguments",
                                    "additionalProperties": True,
                                }
                            },
                            "required": ["arguments"],
                        },
                    },
                },
                {
                    "type": "function",
                    "function": {
                        "description": "Echo a message as a resource",
                        "name": "echo_resource",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "uri": {
                                    "type": "string",
                                    "description": "A URI template (according to RFC 6570) that can be used to construct resource URIs.\nHere is the correct format for the URI template:\necho://{message}\n",
                                }
                            },
                            "required": ["uri"],
                        },
                    },
                },
            ]
            assert agent.llm_config["tools"] == expected_schema  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_convert_resource(self, server_params: "StdioServerParameters") -> None:  # type: ignore[no-any-unimported]
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            # Initialize the connection
            await session.initialize()
            toolkit = await create_toolkit(session=session)
            echo_resource_tool = toolkit.get_tool("echo_resource")
            assert echo_resource_tool is not None
            assert echo_resource_tool.name == "echo_resource"

            result = await echo_resource_tool(uri="echo://AG2User")
            assert isinstance(result, ReadResourceResult)
            expected_result = [
                TextResourceContents(uri=AnyUrl("echo://AG2User"), mimeType="text/plain", text="Resource echo: AG2User")
            ]
            assert result.contents == expected_result

    @pytest.mark.asyncio
    @pytest.mark.skipif("OPENAI_API_KEY" not in os.environ, reason="OPENAI_API_KEY not set, skipping integration test.")
    async def test_register_for_llm_tool(
        self, server_params: "StdioServerParameters", credentials_gpt_4o_mini: Credentials
    ) -> None:  # type: ignore[no-any-unimported]
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            # Initialize the connection
            await session.initialize()
            toolkit = await create_toolkit(session=session)
            agent = AssistantAgent(
                name="agent",
                llm_config=credentials_gpt_4o_mini.llm_config,
            )
            toolkit.register_for_llm(agent)
            assert len(agent.tools) == len(toolkit.tools)

    @pytest.mark.asyncio
    async def test_convert_resource_with_download_folder(self, server_params: "StdioServerParameters") -> None:  # type: ignore[no-any-unimported]
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            await session.initialize()
            with tempfile.TemporaryDirectory() as tmp:
                temp_path = Path(tmp)
                temp_path.mkdir(parents=True, exist_ok=True)
                toolkit = await create_toolkit(session=session, resource_download_folder=temp_path)
                echo_resource_tool = toolkit.get_tool("echo_resource")
                result = await echo_resource_tool(uri="echo://AG2User")
                assert isinstance(result, ResultSaved)

                async with await anyio.open_file(result.file_path, "r") as f:
                    content = await f.read()
                    parsed = json.loads(content)
                    loaded_result = ReadResourceResult.model_validate(parsed)

                    expected_result = [
                        TextResourceContents(
                            uri=AnyUrl("echo://AG2User"),
                            mimeType="text/plain",
                            text="Resource echo: AG2User",
                            meta=None,
                        )
                    ]
                    assert loaded_result.contents == expected_result

    @pytest.mark.asyncio
    @pytest.mark.skipif("OPENAI_API_KEY" not in os.environ, reason="OPENAI_API_KEY not set, skipping integration test.")
    @run_for_optional_imports("openai", "openai")
    async def test_with_llm(self, server_params: "StdioServerParameters", credentials_gpt_4o_mini: Credentials) -> None:  # type: ignore[no-any-unimported]
        async with (
            stdio_client(server_params) as (read, write),
            ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session,
        ):
            # Initialize the connection
            await session.initialize()
            toolkit = await create_toolkit(session=session)

            agent = AssistantAgent(
                name="agent",
                llm_config=credentials_gpt_4o_mini.llm_config,
            )
            toolkit.register_for_llm(agent)

            result = await agent.a_run(
                message="What is 1234 + 5678?",
                tools=toolkit.tools,
                max_turns=3,
                user_input=False,
                summary_method="reflection_with_llm",
            )
            await result.process()
            summary = await result.summary
            assert "6912" in summary


class TestMCPClientSessionManager:
    @pytest.mark.asyncio
    async def test_create_stdio_session(self):
        import sys

        from autogen.mcp.mcp_client import MCPClientSessionManager, StdioConfig

        if sys.platform == "win32":
            pytest.skip("Skipping stdio session test on Windows.")
        # Use the math_server.py as a dummy server
        server_file = Path(__file__).parent / "math_server.py"
        config = StdioConfig(
            command="python3",
            args=[str(server_file)],
            transport="stdio",
            server_name="test_server",
        )
        manager = MCPClientSessionManager()
        async with manager.create_stdio_session(config) as session:
            assert session is not None

    @pytest.mark.asyncio
    async def test_open_session(self):
        import sys

        from autogen.mcp.mcp_client import MCPClientSessionManager, StdioConfig

        if sys.platform == "win32":
            pytest.skip("Skipping open_session test on Windows.")
        server_file = Path(__file__).parent / "math_server.py"
        config = StdioConfig(
            command="python3",
            args=[str(server_file)],
            transport="stdio",
            server_name="test_server",
        )
        manager = MCPClientSessionManager()
        async with manager.open_session(config) as session:
            assert session is not None


def test_stdioconfig_creation():
    from autogen.mcp.mcp_client import StdioConfig

    config = StdioConfig(
        command="python3",
        args=["script.py", "--foo", "bar"],
        transport="stdio",
        server_name="test_server",
        environment={"ENV_VAR": "value"},
        working_dir="/tmp",
        encoding="utf-8",
        encoding_error_handler="strict",
        session_options={"read_timeout_seconds": 10},
    )
    assert config.command == "python3"
    assert config.args == ["script.py", "--foo", "bar"]
    assert config.transport == "stdio"
    assert config.server_name == "test_server"
    assert config.environment["ENV_VAR"] == "value"
    assert config.working_dir == "/tmp"
    assert config.encoding == "utf-8"
    assert config.encoding_error_handler == "strict"
    assert config.session_options["read_timeout_seconds"] == 10


def test_mcpconfig_creation():
    from autogen.mcp.mcp_client import MCPConfig, StdioConfig

    stdio_cfg = StdioConfig(
        command="python3",
        args=["script.py"],
        transport="stdio",
        server_name="server1",
    )
    mcp_cfg = MCPConfig(servers=[stdio_cfg])
    assert len(mcp_cfg.servers) == 1
    assert mcp_cfg.servers[0].server_name == "server1"
