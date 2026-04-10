import asyncio
import os
import sys

import cloudpickle

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def verify_agent(name, dir_path):
    print(f"\n--- Testing {name} ---")
    import importlib.util

    # Load dynamically like deploy_agent_engine.py
    module_name = f"main_{name}"
    spec = importlib.util.spec_from_file_location(
        module_name, os.path.join(project_root, dir_path, "main.py")
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    # Register by value
    cloudpickle.register_pickle_by_value(module)
    agent_obj = module.agent

    # Pickle
    pickled = cloudpickle.dumps(agent_obj)
    print(f"Pickled size: {len(pickled)}")

    # Clean environment
    for m in list(sys.modules.keys()):
        if m.startswith("agents") or m.startswith("testbed_utils") or m == module_name:
            del sys.modules[m]
    if project_root in sys.path:
        sys.path.remove(project_root)

    # Load
    try:
        unpickled_agent = cloudpickle.loads(pickled)
        print("✅ Load successful in clean env")
        return unpickled_agent
    except Exception as e:
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
