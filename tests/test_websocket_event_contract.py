import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from src.memory.user_profile import _DEFAULTS


class _DummyWatcher:
    def stop(self):
        return None

    def join(self):
        return None


class _ChunkMessageAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "router"},
            "data": {},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "router"},
            "data": {
                "output": {
                    "router_metadata": {
                        "route": "complex-default",
                        "confidence": 0.87,
                        "reasoning": "llm_classified_complex:coding",
                        "classification_source": "llm_classifier",
                        "cloud_available": True,
                        "features": {
                            "has_images": False,
                            "task_category": "coding",
                            "estimated_tokens": 4096,
                            "web_intent": False,
                        },
                    }
                }
            },
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "simple"},
            "data": {"chunk": AIMessageChunk(content="hello")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "simple"},
            "data": {
                "output": {
                    "messages": [AIMessage(content="hello from contract test")],
                    "model_used": "test-model",
                    "fallback_chain": [
                        {"model": "test-model", "status": "success", "reason": "direct", "duration_ms": 5},
                    ],
                }
            },
        }


class _RouterInfoAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "router"},
            "data": {
                "output": {
                    "router_metadata": {
                        "route": "simple",
                        "confidence": 0.98,
                        "reasoning": "keyword_match",
                        "swap_decision": "not_needed",
                        "swap_from": None,
                        "swap_to": None,
                        "classification_source": "keyword_bypass",
                        "token_budget": 256,
                        "cloud_available": False,
                        "features": {
                            "has_images": False,
                            "task_category": "greeting",
                            "estimated_tokens": 256,
                            "web_intent": False,
                        },
                    }
                }
            },
        }
        yield {
            "event": "on_chat_model_stream",
            "metadata": {"langgraph_node": "simple"},
            "data": {"chunk": AIMessageChunk(content="hi")},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "simple"},
            "data": {
                "output": {
                    "messages": [AIMessage(content="hi there")],
                    "model_used": "small-local",
                    "fallback_chain": [
                        {"model": "small-local", "status": "success", "reason": "simple_route", "duration_ms": 42},
                    ],
                }
            },
        }


class _FallbackChainAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "complex_llm"},
            "data": {
                "output": {
                    "messages": [AIMessage(content="fallback response")],
                    "model_used": "medium-default-fallback",
                    "fallback_chain": [
                        {"model": "large-cloud", "status": "failed", "reason": "API key invalid", "duration_ms": 42},
                        {"model": "medium-default-fallback", "status": "success", "reason": "fallback", "duration_ms": 8},
                    ],
                }
            },
        }


class _ToolAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        ai_msg = AIMessage(
            content="I'll run a tool.",
            tool_calls=[{"id": "tool-call-1", "name": "read_workspace_file", "args": {"path": "README.md"}}],
        )
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "complex_llm"},
            "data": {"output": {"messages": [ai_msg], "model_used": "test-model"}},
        }
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "tools"},
            "data": {},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "tools"},
            "data": {
                "output": {
                    "messages": [
                        ToolMessage(
                            content="ok",
                            tool_call_id="tool-call-1",
                            name="read_workspace_file",
                        )
                    ]
                }
            },
        }


class _RiskyToolAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        ai_msg = AIMessage(
            content="Deleting file",
            tool_calls=[{"id": "tool-call-risk-1", "name": "delete_workspace_file", "args": {"filename": "danger.txt"}}],
        )
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "complex_llm"},
            "data": {"output": {"messages": [ai_msg], "model_used": "test-model"}},
        }
        yield {
            "event": "on_chain_start",
            "metadata": {"langgraph_node": "tools"},
            "data": {},
        }
        yield {
            "event": "on_chain_end",
            "metadata": {"langgraph_node": "tools"},
            "data": {
                "output": {
                    "messages": [
                        ToolMessage(
                            content="ok",
                            tool_call_id="tool-call-risk-1",
                            name="delete_workspace_file",
                        )
                    ]
                }
            },
        }


class _InterruptAgent:
    async def astream_events(self, _input_data, config=None, version="v2"):
        yield {
            "event": "on_chain_stream",
            "metadata": {"langgraph_node": "security_proxy"},
            "data": {
                "chunk": {
                    "__interrupt__": [
                        {
                            "type": "security_approval_required",
                            "sensitive_tool_calls": [
                                {
                                    "name": "delete_workspace_file",
                                    "args": {"filename": "danger.txt"},
                                    "risk_label": "destructive_action",
                                    "risk_confidence": 0.98,
                                    "risk_rationale": "Delete semantics detected by security policy.",
                                    "remediation_hint": "Confirm target path and backup before execution.",
                                }
                            ],
                        }
                    ]
                }
            },
        }


@contextmanager
def _client_with_agent(tmp_path, fake_agent):
    from src.api.server import app

    tmp_profile = tmp_path / "user_profile.json"
    tmp_profile.write_text(json.dumps(_DEFAULTS), encoding="utf-8")
    with patch("src.memory.user_profile._PROFILE_PATH", tmp_profile), patch(
        "src.api.server.init_agent", autospec=True
    ) as init_agent_mock, patch(
        "src.api.server.start_watcher", autospec=True
    ) as watcher_mock:
        init_agent_mock.return_value = fake_agent
        watcher_mock.return_value = _DummyWatcher()
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


def _collect_ws_events(ws, max_events=40):
    events = []
    for _ in range(max_events):
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == "status" and event.get("content") == "idle":
            break
    return events


def test_ws_event_lifecycle_has_reasoning_and_idle(tmp_path):
    with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-lifecycle") as ws:
            ws.send_text(json.dumps({"message": "hello"}))
            events = _collect_ws_events(ws)

    statuses = [e.get("content") for e in events if e.get("type") == "status"]
    assert statuses and statuses[0] == "reasoning"
    assert "idle" in statuses


def test_ws_chunk_and_final_message_contract(tmp_path):
    with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-chunk-message") as ws:
            ws.send_text(json.dumps({"message": "hello"}))
            events = _collect_ws_events(ws)

    chunk_events = [e for e in events if e.get("type") == "chunk"]
    assert chunk_events and isinstance(chunk_events[0].get("content"), str)

    message_events = [e for e in events if e.get("type") == "message"]
    assert message_events
    payload = message_events[-1].get("message")
    assert isinstance(payload, dict)
    assert payload.get("type")
    assert isinstance(payload.get("content", ""), str)


def test_ws_tool_execution_running_to_terminal_contract(tmp_path):
    with _client_with_agent(tmp_path, _ToolAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-tool-contract") as ws:
            ws.send_text(json.dumps({"message": "use a tool"}))
            events = _collect_ws_events(ws)

    running = [e for e in events if e.get("type") == "tool_execution" and e.get("status") == "running"]
    terminal = [e for e in events if e.get("type") == "tool_execution" and e.get("status") in {"success", "error"}]
    assert running and terminal
    assert running[0].get("tool_name")
    assert running[0].get("tool_call_id")
    assert terminal[-1].get("tool_call_id") == running[0].get("tool_call_id")


def test_ws_tool_execution_running_includes_risk_metadata_when_detected(tmp_path):
    with _client_with_agent(tmp_path, _RiskyToolAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-tool-risk") as ws:
            ws.send_text(json.dumps({"message": "delete this file"}))
            events = _collect_ws_events(ws)

    running = [e for e in events if e.get("type") == "tool_execution" and e.get("status") == "running"]
    assert running
    payload = running[0]
    assert payload.get("tool_name") == "delete_workspace_file"
    assert payload.get("risk_label") == "destructive_action"
    assert isinstance(payload.get("risk_confidence"), float)
    assert isinstance(payload.get("risk_rationale"), str)
    assert isinstance(payload.get("remediation_hint"), str)


def test_ws_payload_defaults_when_optional_fields_missing(tmp_path):
    with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-defaults") as ws:
            ws.send_text(json.dumps({"message": "hello defaults"}))
            events = _collect_ws_events(ws)

    assert any(e.get("type") == "status" and e.get("content") == "idle" for e in events)
    assert not any(e.get("type") == "error" for e in events)


def test_ws_interrupt_contract_contains_backend_risk_metadata(tmp_path):
    with _client_with_agent(tmp_path, _InterruptAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-interrupt-risk") as ws:
            ws.send_text(json.dumps({"message": "run sensitive tool"}))
            events = _collect_ws_events(ws)

    interrupt_events = [e for e in events if e.get("type") == "interrupt"]
    assert interrupt_events
    payload = interrupt_events[-1].get("interrupts", [])[0]
    assert payload.get("type") == "security_approval_required"
    assert payload.get("tool_name") == "delete_workspace_file"
    assert payload.get("tool_args")
    assert payload.get("risk_label") == "destructive_action"
    assert isinstance(payload.get("risk_confidence"), float)
    assert isinstance(payload.get("risk_rationale"), str)
    assert isinstance(payload.get("remediation_hint"), str)


def test_ask_user_response_preserves_structured_answer(tmp_path):
    captured_inputs = []

    async def _capture_start_run(self, input_data, config):
        captured_inputs.append(input_data)

    with patch("src.api.server.GraphSession.start_run", new=_capture_start_run):
        with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
            with client.websocket_connect("/ws/chat/ws-ask-user") as ws:
                ws.send_text(
                    json.dumps(
                        {
                            "type": "ask_user_response",
                            "answer": {"route": "complex", "toolbox": "tools_on"},
                        }
                    )
                )

    assert captured_inputs
    resume = getattr(captured_inputs[0], "resume", None)
    assert isinstance(resume, dict)
    assert resume.get("answer") == {"route": "complex", "toolbox": "tools_on"}


def test_ws_interleaved_messages_preserve_project_context_per_payload(tmp_path):
    captured_inputs = []

    async def _capture_start_run(self, input_data, config):
        captured_inputs.append(input_data)

    with patch("src.api.server.GraphSession.start_run", new=_capture_start_run):
        with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
            with client.websocket_connect("/ws/chat/ws-project-interleave") as ws:
                ws.send_text(json.dumps({"message": "first", "project_id": "proj-alpha"}))
                ws.send_text(json.dumps({"message": "second", "project_id": "proj-beta"}))

    dict_runs = [item for item in captured_inputs if isinstance(item, dict) and "message" not in item]
    assert len(dict_runs) >= 2
    assert dict_runs[0].get("project_id") == "proj-alpha"
    assert dict_runs[1].get("project_id") == "proj-beta"


def test_ws_and_project_crud_interleaving_preserves_project_isolation(tmp_path):
    captured_inputs = []

    async def _capture_start_run(self, input_data, config):
        captured_inputs.append(input_data)

    with patch("src.api.server.GraphSession.start_run", new=_capture_start_run):
        with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
            # Explorer-like CRUD flow across two projects.
            proj_a = client.post("/api/projects", json={"name": "Interleave A"}).json()
            proj_b = client.post("/api/projects", json={"name": "Interleave B"}).json()
            pid_a = proj_a["id"]
            pid_b = proj_b["id"]

            client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-1", "name": "A 1", "created_at": 1.0})
            client.post(f"/api/projects/{pid_b}/chats", json={"id": "b-1", "name": "B 1", "created_at": 1.0})
            client.put(f"/api/projects/{pid_a}/chats/a-1", json={"name": "A 1 updated"})
            client.delete(f"/api/projects/{pid_b}/chats/b-1")

            with client.websocket_connect("/ws/chat/ws-crud-project-interleave") as ws:
                ws.send_text(json.dumps({"message": "run in A", "project_id": pid_a}))
                ws.send_text(json.dumps({"message": "run in B", "project_id": pid_b}))
                ws.send_text(json.dumps({"message": "back to A", "project_id": pid_a}))

            dict_runs = [item for item in captured_inputs if isinstance(item, dict) and "message" not in item]
            assert len(dict_runs) >= 3
            assert dict_runs[0].get("project_id") == pid_a
            assert dict_runs[1].get("project_id") == pid_b
            assert dict_runs[2].get("project_id") == pid_a

            # Verify CRUD isolation remained intact while websocket payloads interleaved.
            final_a = client.get(f"/api/projects/{pid_a}").json()
            final_b = client.get(f"/api/projects/{pid_b}").json()

            assert any(chat.get("id") == "a-1" for chat in final_a.get("chats", []))
            assert all(str(chat.get("id", "")).startswith("a-") for chat in final_a.get("chats", []))

            assert not any(chat.get("id") == "b-1" for chat in final_b.get("chats", []))
            assert all(str(chat.get("id", "")).startswith("b-") for chat in final_b.get("chats", []))


def test_ws_deterministic_multi_switch_sweep_keeps_project_context_and_crud_isolation(tmp_path):
    captured_inputs = []

    async def _capture_start_run(self, input_data, config):
        captured_inputs.append(input_data)

    with patch("src.api.server.GraphSession.start_run", new=_capture_start_run):
        with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
            proj_a = client.post("/api/projects", json={"name": "Sweep A"}).json()
            proj_b = client.post("/api/projects", json={"name": "Sweep B"}).json()
            proj_c = client.post("/api/projects", json={"name": "Sweep C"}).json()
            pid_a = proj_a["id"]
            pid_b = proj_b["id"]
            pid_c = proj_c["id"]

            # Explorer-like baseline chat setup across three projects.
            client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-1", "name": "A 1", "created_at": 1.0})
            client.post(f"/api/projects/{pid_b}/chats", json={"id": "b-1", "name": "B 1", "created_at": 1.0})
            client.post(f"/api/projects/{pid_c}/chats", json={"id": "c-1", "name": "C 1", "created_at": 1.0})

            with client.websocket_connect("/ws/chat/ws-multi-switch-sweep") as ws:
                # Deterministic interleaving sequence: A -> B -> C -> B -> A -> C
                ws.send_text(json.dumps({"message": "run-A-1", "project_id": pid_a}))
                client.put(f"/api/projects/{pid_b}/chats/b-1", json={"name": "B 1 updated"})

                ws.send_text(json.dumps({"message": "run-B-1", "project_id": pid_b}))
                client.post(f"/api/projects/{pid_c}/chats", json={"id": "c-2", "name": "C 2", "created_at": 2.0})

                ws.send_text(json.dumps({"message": "run-C-1", "project_id": pid_c}))
                client.delete(f"/api/projects/{pid_a}/chats/a-1")
                client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-2", "name": "A 2", "created_at": 2.0})

                ws.send_text(json.dumps({"message": "run-B-2", "project_id": pid_b}))
                client.delete(f"/api/projects/{pid_c}/chats/c-1")

                ws.send_text(json.dumps({"message": "run-A-2", "project_id": pid_a}))
                ws.send_text(json.dumps({"message": "run-C-2", "project_id": pid_c}))

            dict_runs = [item for item in captured_inputs if isinstance(item, dict) and "message" not in item]
            assert len(dict_runs) >= 6
            ordered_project_ids = [item.get("project_id") for item in dict_runs[:6]]
            assert ordered_project_ids == [pid_a, pid_b, pid_c, pid_b, pid_a, pid_c]

            final_a = client.get(f"/api/projects/{pid_a}").json()
            final_b = client.get(f"/api/projects/{pid_b}").json()
            final_c = client.get(f"/api/projects/{pid_c}").json()

            chats_a = final_a.get("chats", [])
            chats_b = final_b.get("chats", [])
            chats_c = final_c.get("chats", [])

            # A: deleted a-1 and replaced with a-2 only.
            assert not any(chat.get("id") == "a-1" for chat in chats_a)
            assert any(chat.get("id") == "a-2" for chat in chats_a)
            assert all(str(chat.get("id", "")).startswith("a-") for chat in chats_a)

            # B: b-1 remains and was updated, isolation intact.
            assert any(chat.get("id") == "b-1" and chat.get("name") == "B 1 updated" for chat in chats_b)
            assert all(str(chat.get("id", "")).startswith("b-") for chat in chats_b)

            # C: c-1 deleted, c-2 retained, isolation intact.
            assert not any(chat.get("id") == "c-1" for chat in chats_c)
            assert any(chat.get("id") == "c-2" for chat in chats_c)
            assert all(str(chat.get("id", "")).startswith("c-") for chat in chats_c)


def test_ws_high_pressure_interleaving_preserves_ordered_project_context_and_crud_state(tmp_path):
    captured_inputs = []

    async def _capture_start_run(self, input_data, config):
        captured_inputs.append(input_data)

    with patch("src.api.server.GraphSession.start_run", new=_capture_start_run):
        with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
            proj_a = client.post("/api/projects", json={"name": "Pressure A"}).json()
            proj_b = client.post("/api/projects", json={"name": "Pressure B"}).json()
            proj_c = client.post("/api/projects", json={"name": "Pressure C"}).json()
            pid_a = proj_a["id"]
            pid_b = proj_b["id"]
            pid_c = proj_c["id"]

            client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-1", "name": "A 1", "created_at": 1.0})
            client.post(f"/api/projects/{pid_b}/chats", json={"id": "b-1", "name": "B 1", "created_at": 1.0})
            client.post(f"/api/projects/{pid_c}/chats", json={"id": "c-1", "name": "C 1", "created_at": 1.0})

            sequence = [pid_a, pid_b, pid_c, pid_a, pid_c, pid_b, pid_a, pid_b, pid_c, pid_b, pid_a, pid_c]
            with client.websocket_connect("/ws/chat/ws-high-pressure-interleave") as ws:
                ws.send_text(json.dumps({"message": "p-a-1", "project_id": pid_a}))
                client.put(f"/api/projects/{pid_b}/chats/b-1", json={"name": "B 1 u1"})

                ws.send_text(json.dumps({"message": "p-b-1", "project_id": pid_b}))
                client.post(f"/api/projects/{pid_c}/chats", json={"id": "c-2", "name": "C 2", "created_at": 2.0})

                ws.send_text(json.dumps({"message": "p-c-1", "project_id": pid_c}))
                client.delete(f"/api/projects/{pid_a}/chats/a-1")
                client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-2", "name": "A 2", "created_at": 2.0})

                ws.send_text(json.dumps({"message": "p-a-2", "project_id": pid_a}))
                client.put(f"/api/projects/{pid_c}/chats/c-2", json={"name": "C 2 u1"})

                ws.send_text(json.dumps({"message": "p-c-2", "project_id": pid_c}))
                client.post(f"/api/projects/{pid_b}/chats", json={"id": "b-2", "name": "B 2", "created_at": 2.0})

                ws.send_text(json.dumps({"message": "p-b-2", "project_id": pid_b}))
                client.delete(f"/api/projects/{pid_c}/chats/c-1")

                ws.send_text(json.dumps({"message": "p-a-3", "project_id": pid_a}))
                client.put(f"/api/projects/{pid_a}/chats/a-2", json={"name": "A 2 u1"})

                ws.send_text(json.dumps({"message": "p-b-3", "project_id": pid_b}))
                client.delete(f"/api/projects/{pid_b}/chats/b-1")

                ws.send_text(json.dumps({"message": "p-c-3", "project_id": pid_c}))
                client.post(f"/api/projects/{pid_a}/chats", json={"id": "a-3", "name": "A 3", "created_at": 3.0})

                ws.send_text(json.dumps({"message": "p-b-4", "project_id": pid_b}))
                client.put(f"/api/projects/{pid_b}/chats/b-2", json={"name": "B 2 u1"})

                ws.send_text(json.dumps({"message": "p-a-4", "project_id": pid_a}))
                ws.send_text(json.dumps({"message": "p-c-4", "project_id": pid_c}))

            dict_runs = [item for item in captured_inputs if isinstance(item, dict) and "message" not in item]
            assert len(dict_runs) >= len(sequence)
            ordered_project_ids = [item.get("project_id") for item in dict_runs[: len(sequence)]]
            assert ordered_project_ids == sequence

            final_a = client.get(f"/api/projects/{pid_a}").json()
            final_b = client.get(f"/api/projects/{pid_b}").json()
            final_c = client.get(f"/api/projects/{pid_c}").json()

            chats_a = final_a.get("chats", [])
            chats_b = final_b.get("chats", [])
            chats_c = final_c.get("chats", [])

            assert not any(chat.get("id") == "a-1" for chat in chats_a)
            assert any(chat.get("id") == "a-2" and chat.get("name") == "A 2 u1" for chat in chats_a)
            assert any(chat.get("id") == "a-3" for chat in chats_a)
            assert all(str(chat.get("id", "")).startswith("a-") for chat in chats_a)

            assert not any(chat.get("id") == "b-1" for chat in chats_b)
            assert any(chat.get("id") == "b-2" and chat.get("name") == "B 2 u1" for chat in chats_b)
            assert all(str(chat.get("id", "")).startswith("b-") for chat in chats_b)

            assert not any(chat.get("id") == "c-1" for chat in chats_c)
            assert any(chat.get("id") == "c-2" and chat.get("name") == "C 2 u1" for chat in chats_c)
            assert all(str(chat.get("id", "")).startswith("c-") for chat in chats_c)


def test_ws_router_info_event_emitted(tmp_path):
    """router_info event is emitted when router_metadata is present in router node output."""
    with _client_with_agent(tmp_path, _RouterInfoAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-router-info") as ws:
            ws.send_text(json.dumps({"message": "hi"}))
            events = _collect_ws_events(ws)

    router_info_events = [e for e in events if e.get("type") == "router_info"]
    assert router_info_events
    payload = router_info_events[0]
    metadata = payload.get("metadata", {})
    assert metadata.get("route") == "simple"
    assert metadata.get("confidence") == 0.98
    assert metadata.get("classification_source") == "keyword_bypass"
    assert metadata.get("features", {}).get("task_category") == "greeting"
    assert "reasoning" in metadata


def test_ws_router_info_contains_reasoning_key(tmp_path):
    """router_info metadata must contain a reasoning field."""
    with _client_with_agent(tmp_path, _RouterInfoAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-router-reasoning") as ws:
            ws.send_text(json.dumps({"message": "hi"}))
            events = _collect_ws_events(ws)

    router_info_events = [e for e in events if e.get("type") == "router_info"]
    assert router_info_events
    metadata = router_info_events[0].get("metadata", {})
    assert isinstance(metadata.get("reasoning"), str)
    assert len(metadata["reasoning"]) > 0


def test_ws_model_info_includes_fallback_chain(tmp_path):
    """model_info event includes fallback_chain when the complex node returns one."""
    with _client_with_agent(tmp_path, _FallbackChainAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-fallback-chain") as ws:
            ws.send_text(json.dumps({"message": "trigger fallback"}))
            events = _collect_ws_events(ws)

    model_info_events = [e for e in events if e.get("type") == "model_info"]
    assert model_info_events
    model_info = model_info_events[-1]
    assert model_info.get("model") == "medium-default-fallback"
    fallback_chain = model_info.get("fallback_chain")
    assert fallback_chain and isinstance(fallback_chain, list)
    assert len(fallback_chain) >= 2
    # First entry is a failure
    assert fallback_chain[0].get("status") == "failed"
    assert "model" in fallback_chain[0]
    assert "reason" in fallback_chain[0]
    # Last entry is success
    assert fallback_chain[-1].get("status") == "success"
    assert fallback_chain[-1].get("model") == "medium-default-fallback"


def test_ws_fallback_chain_entry_shape(tmp_path):
    """Each fallback_chain entry has the required fields (model, status, reason, duration_ms)."""
    with _client_with_agent(tmp_path, _FallbackChainAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-fallback-shape") as ws:
            ws.send_text(json.dumps({"message": "check shape"}))
            events = _collect_ws_events(ws)

    model_info_events = [e for e in events if e.get("type") == "model_info"]
    assert model_info_events
    chain = model_info_events[-1].get("fallback_chain", [])
    for entry in chain:
        assert isinstance(entry.get("model"), str) and entry["model"]
        assert entry.get("status") in ("success", "failed", "skipped")
        assert isinstance(entry.get("reason"), str)
        assert isinstance(entry.get("duration_ms"), int)
        assert entry["duration_ms"] >= 0


def test_ws_error_event_shape(tmp_path):
    """error event must have type='error' and a string content field."""
    with _client_with_agent(tmp_path, _ChunkMessageAgent()) as client:
        with client.websocket_connect("/ws/chat/ws-error-shape") as ws:
            ws.send_text(json.dumps({"message": "hello"}))
            events = _collect_ws_events(ws)

    error_events = [e for e in events if e.get("type") == "error"]
    for err in error_events:
        assert isinstance(err.get("content"), str)
        assert err["content"].strip()
