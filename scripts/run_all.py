import subprocess
import os
import sys
import time

def main():
    """Runs all Agents and MCP servers locally using uvicorn on specific ports."""
    
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    services = [
        # Agents
        {"name": "RootRouter", "path": "agents/RootRouter", "port": 8080},
        {"name": "BookingOrchestrator", "path": "agents/BookingOrchestrator", "port": 8081},
        {"name": "FlightSpecialist", "path": "agents/FlightSpecialist", "port": 8082},
        {"name": "WeatherSpecialist", "path": "agents/WeatherSpecialist", "port": 8083},
        {"name": "HotelSpecialist", "path": "agents/HotelSpecialist", "port": 8084},
        {"name": "CarRentalSpecialist", "path": "agents/CarRentalSpecialist", "port": 8085},
        
        # MCP Servers
        {"name": "Profile_MCP", "path": "mcp_servers/Profile_MCP", "port": 8090},
        {"name": "Inventory_MCP", "path": "mcp_servers/Inventory_MCP", "port": 8091},
    ]

    processes = []
    
    print("🚀 Starting all testbed services locally...")
    
    # Optional: ensure python-dotenv is loaded by uvicorn by installing it in the venv
    
    try:
        for svc in services:
            svc_dir = os.path.join(root_dir, svc["path"])
            if not os.path.exists(svc_dir):
                print(f"⚠️ Warning: Directory not found for {svc['name']} at {svc_dir}")
                continue
            
            print(f"Starting {svc['name']} on port {svc['port']}...")

            # Check if the port is already in use and warn before killing
            check = subprocess.run(
                f"lsof -ti:{svc['port']}", shell=True,
                capture_output=True, text=True
            )
            if check.stdout.strip():
                pids = check.stdout.strip().split('\n')
                print(f"  ⚠️  Port {svc['port']} in use by PID(s): {', '.join(pids)} — terminating...")
                for pid in pids:
                    # Use SIGTERM first for graceful shutdown
                    subprocess.run(["kill", pid.strip()], capture_output=True)
                time.sleep(0.5)
                # Force-kill only if still alive
                for pid in pids:
                    subprocess.run(["kill", "-9", pid.strip()], capture_output=True)
            
            env = os.environ.copy()
            # Override to false locally so setup_telemetry() initializes a provider
            env["GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"] = "false"
            # Uvicorn reads .env natively if python-dotenv is installed, 

            # but we'll also rely on the CLI --env-file if needed, but uvicorn handles it.
            
            p = subprocess.Popen(
                ["uv", "run", "uvicorn", "main:app", "--port", str(svc["port"]), "--env-file", "../../.env"],
                cwd=svc_dir,
                env=env,
                stdout=sys.stdout,
                stderr=sys.stderr
            )
            processes.append(p)
            # Give each service a moment to bind to the port before starting the next
            time.sleep(0.5)
            
        print("\n✅ All services are running! Press Ctrl+C to stop all.")
        print(f"   RootRouter Interface: http://localhost:8080/chat")
        
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Shutting down all services...")
        for p in processes:
            p.terminate()
        for p in processes:
            p.wait()
        print("Done.")

if __name__ == "__main__":
    main()
