from __future__ import annotations

import unittest

from pq_bitedu.agentic import HostedAgentController, MultiAgentEnvironment, build_hosted_adapter, default_provider_config
from pq_bitedu.agentic.providers import GeminiGenerateContentAdapter, OpenAICompatibleChatAdapter


class FakeAdapter(OpenAICompatibleChatAdapter):
    def __init__(self) -> None:
        super().__init__(default_provider_config("deepseek", "deepseek-v4-flash"))
        self.call_count = 0

    def ping(self):
        return {"ok": True}

    def _request(self, path, payload, method):
        self.call_count += 1
        self.last_path = path
        self.last_payload = payload
        self.last_method = method
        return {
            "choices": [
                {
                    "message": {
                        "content": "直接转账",
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "send_transaction",
                                    "arguments": "{\"recipient\":\"peer\",\"amount\":1,\"fee\":0}",
                                },
                            }
                        ],
                    }
                }
            ]
        }


class HostedProviderTests(unittest.TestCase):
    def test_build_hosted_adapter_for_deepseek(self) -> None:
        adapter = build_hosted_adapter(default_provider_config("deepseek", "deepseek-v4-flash"))
        self.assertIsInstance(adapter, OpenAICompatibleChatAdapter)

    def test_build_hosted_adapter_for_gemini(self) -> None:
        adapter = build_hosted_adapter(default_provider_config("gemini", "gemini-2.5-flash"))
        self.assertIsInstance(adapter, GeminiGenerateContentAdapter)

    def test_gemini_adapter_sanitizes_openai_style_schema(self) -> None:
        adapter = GeminiGenerateContentAdapter(default_provider_config("gemini", "gemini-2.5-flash"))
        sanitized = adapter._sanitize_parameters(
            {
                "type": "object",
                "properties": {
                    "amount": {
                        "type": "integer",
                        "description": "数量",
                        "additionalProperties": False,
                    }
                },
                "required": ["amount"],
                "additionalProperties": False,
            }
        )
        self.assertNotIn("additionalProperties", sanitized)
        self.assertNotIn("additionalProperties", sanitized["properties"]["amount"])

    def test_hosted_controller_parses_tool_calls(self) -> None:
        environment = MultiAgentEnvironment()
        environment.register_agent(
            name="llm_agent",
            controller=HostedAgentController(FakeAdapter()),
            role="trader",
            objective="Inspect the wallet.",
        )
        environment.register_agent(
            name="peer",
            controller=HostedAgentController(FakeAdapter()),
            role="miner",
            objective="unused",
        )
        environment.initialize_chain("peer", extra_reward_blocks=1)
        environment.transfer("peer", "llm_agent", amount=5, fee=1)
        environment.mine("peer", coinbase_data="seed-llm")
        observation = environment.build_observation("llm_agent")
        decision = environment._runtimes["llm_agent"].controller.plan_turn(observation)
        self.assertEqual(decision.summary, "直接转账")
        self.assertEqual(len(decision.tool_calls), 1)
        self.assertEqual(decision.tool_calls[0].tool_name, "send_transaction")
        environment._runtimes["llm_agent"].controller = HostedAgentController(FakeAdapter())
        planned_decision, results = environment.step_agent("llm_agent")
        self.assertEqual(len(planned_decision.tool_calls), 1)
        self.assertEqual(planned_decision.tool_calls[0].tool_name, "send_transaction")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].tool_name, "send_transaction")


if __name__ == "__main__":
    unittest.main()
