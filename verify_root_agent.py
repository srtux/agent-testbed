import sys
import os
import cloudpickle
import copy

# Add project root to path
sys.path.insert(0, os.getcwd())

print("Importing agent...")
from agents.RootRouter.root_router.agent import agent

print("Attempting deepcopy...")
try:
    copy.deepcopy(agent)
    print("✅ Deepcopy successful")
except Exception as e:
    print(f"❌ Deepcopy failed: {e}")
    import traceback
    traceback.print_exc()

print("\nAttempting cloudpickle.dumps...")
try:
    pickled = cloudpickle.dumps(agent)
    print(f"✅ Pickling successful ({len(pickled)} bytes)")
except Exception as e:
    print(f"❌ Pickling failed: {e}")
    import traceback
    traceback.print_exc()

print("\nAttempting AdkApp wrapping...")
try:
    from vertexai.preview.reasoning_engines import AdkApp
    app = AdkApp(agent=agent)
    print("✅ AdkApp wrapping successful")
    # Try to pickle the AdkApp too
    print("Attempting cloudpickle.dumps(AdkApp)...")
    pickled_app = cloudpickle.dumps(app)
    print(f"✅ AdkApp pickling successful ({len(pickled_app)} bytes)")
except Exception as e:
    print(f"❌ AdkApp failed: {e}")
    import traceback
    traceback.print_exc()
