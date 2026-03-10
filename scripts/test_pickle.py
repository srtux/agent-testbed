
import os
import sys
import cloudpickle
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from agents.RootRouter.main import agent as root_router_agent

pickled = cloudpickle.dumps(root_router_agent)
print(f"Pickled size: {len(pickled)}")

# Try to load it in a clean environment (simulated)
# Remove agents from sys.modules
for m in list(sys.modules.keys()):
    if m.startswith("agents") or m.startswith("testbed_utils"):
        del sys.modules[m]

# Remove project_root from path
if project_root in sys.path:
    sys.path.remove(project_root)

try:
    cloudpickle.loads(pickled)
    print("✅ Load successful in clean env")
except Exception as e:
    print(f"❌ Load failed: {e}")

# Now add a dummy path to simulate extra_packages
dummy_path = os.path.join(project_root, "dummy_staging")
if os.path.exists(dummy_path):
    import shutil
    shutil.rmtree(dummy_path)
os.makedirs(dummy_path)
os.makedirs(os.path.join(dummy_path, "agents"))
with open(os.path.join(dummy_path, "agents", "__init__.py"), "w") as f: f.write("")

sys.path.append(dummy_path)
try:
    cloudpickle.loads(pickled)
    print("✅ Load successful with dummy_path")
except Exception as e:
    print(f"❌ Load failed with dummy_path: {e}")
