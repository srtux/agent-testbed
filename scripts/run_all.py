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
            
            # Ensure the port is free before starting to avoid [Errno 48]
            # Use lsof -t to get PIDs on the target port and kill them
            subprocess.run(f"lsof -ti:{svc['port']} | xargs kill -9 2>/dev/null", shell=True)
            
            env = os.environ.copy()
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
