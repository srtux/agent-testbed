import os
import sys
import subprocess
import shutil
from pathlib import Path

def run_command(command, cwd=None, env=None, check=True):
    """Runs a shell command and returns the output."""
    print(f"Executing: {' '.join(command)} in {cwd or os.getcwd()}")
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env or os.environ.copy(),
            check=check,
            capture_output=False,
            text=True
        )
    except subprocess.CalledProcessError as e:
        print(f"❌ Error executing command: {e}")
        if check:
            sys.exit(1)
        return None

def main():
    """Builds images, packages resources, and deploys using Terraform."""
    root_dir = Path(__file__).parent.parent.absolute()
    terraform_dir = root_dir / "terraform"
    
    # Load environment variables from .env
    env = os.environ.copy()
    env_file = root_dir / ".env"
    if env_file.exists():
        with open(env_file, "r") as f:
            for line in f:
                if "=" in line and not line.strip().startswith("#"):
                    key, value = line.strip().split("=", 1)
                    env[key] = value

    project_id = env.get("PROJECT_ID", env.get("GOOGLE_CLOUD_PROJECT"))
    region = env.get("REGION", env.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    cluster_name = env.get("CLUSTER_NAME", "default-cluster")

    if not project_id:
        print("❌ Error: PROJECT_ID or GOOGLE_CLOUD_PROJECT must be set in .env")
        sys.exit(1)

    print(f"🚀 Deploying to project: {project_id} in region: {region}")

    # 1. Build and Push Docker Images
    # We assume the images are stored in Artifact Registry or GCR
    # Pattern: gcr.io/PROJECT_ID/IMAGE_NAME or REGION-docker.pkg.dev/PROJECT_ID/REPO/IMAGE_NAME
    # For simplicity, we use the registry path if provided in .env or assume a default GCR path.
    registry_prefix = f"gcr.io/{project_id}"
    
    components = {
        "flight-specialist": "agents/FlightSpecialist",
        "weather-specialist": "agents/WeatherSpecialist",
        "hotel-specialist": "agents/HotelSpecialist",
        "car-rental-specialist": "agents/CarRentalSpecialist",
        "profile-mcp": "mcp_servers/Profile_MCP",
        "inventory-mcp": "mcp_servers/Inventory_MCP",
    }

    image_urls = {}
    
    print("\n📦 Building and pushing Docker images...")
    
    # Check if docker is available AND daemon is running, otherwise fallback to gcloud builds
    use_docker = False
    if shutil.which("docker") is not None:
        try:
            # We run 'docker system info' to check if the daemon is actually reachable
            # We don't check=True here because we want to handle the error ourself.
            result = subprocess.run(
                ["docker", "info"], 
                capture_output=True, 
                text=True, 
                timeout=5
            )
            if result.returncode == 0:
                use_docker = True
            else:
                print(f"⚠️ 'docker' client is present but daemon is unreachable (exit code {result.returncode}).")
        except (subprocess.SubprocessError, Exception):
            print("⚠️ Exception while checking docker daemon status.")
    
    if not use_docker:
        print("💡 Falling back to 'gcloud builds' for container builds...")

    for name, path in components.items():
        image_url = f"{registry_prefix}/{name}:latest"
        image_urls[name.replace("-", "_") + "_image"] = image_url
        
        full_path = root_dir / path
        if not full_path.exists():
            print(f"⚠️ Warning: Directory not found for {name} at {full_path}")
            continue

        dockerfile_path = full_path / "Dockerfile"
        if not dockerfile_path.exists():
            print(f"⚠️ Error: Dockerfile not found for {name} at {dockerfile_path}")
            continue

        if use_docker:
            # Building from project root so it has access to uv.lock and all workspace members
            print(f"Building {name} with docker (from project root)...")
            run_command([
                "docker", "build", 
                "-t", image_url, 
                "-f", str(dockerfile_path),
                "."
            ], cwd=root_dir)
            print(f"Pushing {name}...")
            run_command(["docker", "push", image_url])
        else:
            print(f"Building {name} with gcloud builds submit (from project root)...")
            # Build from root context to handle uv workspace dependencies correctly
            # Since gcloud builds submit doesn't have a --file flag, we copy it temporarily to the root.
            temp_dockerfile = root_dir / "Dockerfile"
            shutil.copy2(dockerfile_path, temp_dockerfile)
            try:
                run_command([
                    "gcloud", "builds", "submit", 
                    "--tag", image_url, 
                    "."
                ], cwd=root_dir)
            finally:
                if temp_dockerfile.exists():
                    os.remove(temp_dockerfile)

    # 2. Package Traffic Generator
    print("\n📦 Packaging Traffic Generator...")
    traffic_gen_dir = root_dir / "traffic_generator"
    zip_path = root_dir / "traffic_generator_source.zip"
    
    if traffic_gen_dir.exists():
        # Zip the directory
        shutil.make_archive(str(root_dir / "traffic_generator_source"), "zip", str(traffic_gen_dir))
        
        # Upload to GCS
        bucket_name = f"{project_id}-deploy-artifacts"
        gcs_path = f"gs://{bucket_name}/traffic_generator_source.zip"
        
        # Ensure bucket exists
        subprocess.run(["gsutil", "mb", "-l", region, f"gs://{bucket_name}"], check=False)
        run_command(["gsutil", "cp", str(zip_path), gcs_path])
        image_urls["traffic_generator_source_zip"] = gcs_path
    else:
        print("⚠️ Warning: traffic_generator directory not found.")
        image_urls["traffic_generator_source_zip"] = "gs://mock/source.zip"

    # 3. Deploy Agent Engine
    print("\n📦 Deploying Agent Engine...")
    
    agent_deploy_command = [
        "uv", "run", "deploy-agent-engine", "--create",
        "--project_id", project_id,
        "--location", region,
        "--bucket", f"{project_id}-deploy-artifacts"
    ]
    
    run_command(agent_deploy_command, cwd=root_dir)

    # 4. Terraform Deploy
    print("\n🏗️ Initializing and Applying Terraform...")
    
    # Initialize
    run_command(["terraform", "init"], cwd=terraform_dir)
    
    # Prepare variables
    tf_vars = [
        "-var", f"project_id={project_id}",
        "-var", f"region={region}",
        "-var", f"cluster_name={cluster_name}",
    ]
    
    for key, value in image_urls.items():
        tf_vars.extend(["-var", f"{key}={value}"])

    # Apply
    run_command(["terraform", "apply", "-auto-approve"] + tf_vars, cwd=terraform_dir)

    print("\n✅ Deployment Complete!")

if __name__ == "__main__":
    main()
