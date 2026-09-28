import unittest
from ledgerd.mcp import MCP, TOOLS, tool_schema


class Wire:
    def call(self, method, path, body):
        return {"method": method, "path": path, "body": body}
    def open_panel(self, panel, body):
        return {"panel": panel, "body": body}


class MCPTests(unittest.TestCase):
    def test_all_narrow_tool_mappings_and_rejected_raw_cypher(self):
        server = MCP(Wire())
        self.assertIn("result", server.dispatch({"jsonrpc": "2.0", "id": 1, "method": "initialize"}))
        for index, name in enumerate(TOOLS, 2):
            schema = tool_schema(name)["inputSchema"]
            args = {key: {} if key == "body" else "fixture:identity" for key in schema["required"]}
            reply = server.dispatch({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                "params": {"name": name, "arguments": args}})
            self.assertFalse(reply["result"]["isError"])
            with self.subTest(tool=name):
                rejected = server.dispatch({"jsonrpc": "2.0", "id": index, "method": "tools/call",
                    "params": {"name": name, "arguments": {**args, "cypher": "CREATE"}}})
                self.assertIn("error", rejected)
        rejected = server.dispatch({"jsonrpc": "2.0", "id": 999, "method": "tools/call",
            "params": {"name": "execute_arbitrary_cypher_write", "arguments": {}}})
        self.assertIn("error", rejected)
