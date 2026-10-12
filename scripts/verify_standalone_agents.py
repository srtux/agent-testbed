import asyncio
import os
import sys

import cloudpickle

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)
os.environ["DISABLE_TELEMETRY"] = "true"


def verify_agent(name, dir_path):
    print(f"\n--- Testing {name} ---")
    import importlib.util

    agent_dir = os.path.abspath(os.path.join(project_root, dir_path))
    agents_root = os.path.join(project_root, "agents")
    sys.path[:] = [
        p
        for p in sys.path
        if not (p.startswith(agents_root) and os.path.abspath(p) != agent_dir)
    ]
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Load dynamically like deploy_agent_engine.py
    module_name = f"main_{name}"
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(agent_dir, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Register by value
    cloudpickle.register_pickle_by_value(module)
    for mod_name, cp_module in list(sys.modules.items()):
        if hasattr(cp_module, "__file__") and cp_module.__file__:
            if cp_module.__file__.startswith(agent_dir):
                cloudpickle.register_pickle_by_value(cp_module)

    import testbed_utils
    import testbed_utils.config
    import testbed_utils.logging
    import testbed_utils.mock_llm
    import testbed_utils.telemetry
    from vertexai.preview.reasoning_engines import AdkApp

    cloudpickle.register_pickle_by_value(testbed_utils)
    cloudpickle.register_pickle_by_value(testbed_utils.telemetry)
    cloudpickle.register_pickle_by_value(testbed_utils.logging)
    cloudpickle.register_pickle_by_value(testbed_utils.config)
    cloudpickle.register_pickle_by_value(testbed_utils.mock_llm)
    cloudpickle.register_pickle_by_value(sys.modules[__name__])

    agent_obj = module.agent
    _setup_auth_transport = testbed_utils.telemetry.setup_authenticated_transport

    class MyAdkApp(AdkApp):
        def clone(self):
            import copy

            return MyAdkApp(
                agent=copy.deepcopy(self._tmpl_attrs.get("agent")),
                enable_tracing=self._tmpl_attrs.get("enable_tracing"),
                session_service_builder=self._tmpl_attrs.get("session_service_builder"),
                artifact_service_builder=self._tmpl_attrs.get(
                    "artifact_service_builder"
                ),
                memory_service_builder=self._tmpl_attrs.get("memory_service_builder"),
                env_vars=self._tmpl_attrs.get("env_vars"),
            )

        def project_id(self):
            proj = self._tmpl_attrs.get("project")
            if proj and not str(proj).isdigit():
                return proj
            return super().project_id()

        def set_up(self):
            _setup_auth_transport()
            return super().set_up()

    import vertexai
    from google.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
    from google.adk.memory.in_memory_memory_service import InMemoryMemoryService
    from google.adk.sessions.in_memory_session_service import InMemorySessionService

    test_project = os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project")
    vertexai.init(project=test_project, location="us-central1")
    adk_app = MyAdkApp(
        agent=agent_obj,
        enable_tracing=False,
        session_service_builder=InMemorySessionService,
        artifact_service_builder=InMemoryArtifactService,
        memory_service_builder=InMemoryMemoryService,
    ).clone()

    # Pickle
    pickled = cloudpickle.dumps(adk_app)
    print(f"Pickled size: {len(pickled)}")

    # Clean environment
    for m in list(sys.modules.keys()):
        if (
            m.startswith("agents")
            or m.startswith("root_router")
            or m.startswith("booking_orchestrator")
            or m.startswith("testbed_utils")
            or m == module_name
        ):
            del sys.modules[m]
    sys.path[:] = [
        p
        for p in sys.path
        if p != project_root and not p.startswith(agents_root)
    ]

    # Load
    try:
        unpickled_app = cloudpickle.loads(pickled)
        print("✅ Load successful in clean env")
        os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ID"] = "3158376837600509952"
        os.environ["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
        os.environ["GOOGLE_CLOUD_PROJECT"] = test_project
        os.environ["GOOGLE_CLOUD_LOCATION"] = "us-central1"
        os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "true"
        unpickled_app.set_up()
        print("✅ MyAdkApp.set_up() succeeded in clean env with numeric GOOGLE_CLOUD_AGENT_ENGINE_ID")
        return unpickled_app._tmpl_attrs.get("agent")
    except Exception as e:
        import traceback

        traceback.print_exc()
        print(f"❌ Load failed: {e}")
        return None


async def main():
    # Test RootRouter
    verify_agent("RootRouter", "agents/RootRouter")

    # Test BookingOrchestrator
    booking_orchestrator = verify_agent(
        "BookingOrchestrator", "agents/BookingOrchestrator"
    )

    if booking_orchestrator:
        print("\n--- Verifying inner tool execution for BookingOrchestrator ---")
        # Find calculate_trip_cost tool
        calculate_trip_cost = None
        for tool in booking_orchestrator.tools:
            # tool might be a function or AgentTool
            if hasattr(tool, "__name__") and tool.__name__ == "calculate_trip_cost":
                calculate_trip_cost = tool
                break
            elif (
                hasattr(tool, "func")
                and hasattr(tool.func, "__name__")
                and tool.func.__name__ == "calculate_trip_cost"
            ):
                calculate_trip_cost = tool.func
                break

        if calculate_trip_cost:
            try:
                # Call it
                print("Calling calculate_trip_cost...")
                result = await calculate_trip_cost(
                    flight_cost=100,
                    hotel_cost=50,
                    car_cost=30,
                    days=2,
                    loyalty_tier="Gold",
                )
                print(f"✅ Tool execution successful! Result: {result}")
            except Exception as e:
                print(f"❌ Tool execution failed: {e}")
        else:
            print("❌ Could not find calculate_trip_cost tool")


if __name__ == "__main__":
    asyncio.run(main())
