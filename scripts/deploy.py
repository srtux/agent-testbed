import os
import sys
import subprocess
import shutil
import concurrent.futures
from pathlib import Path
from datetime import datetime

def run_command(command, cwd=None, env=None, check=True, log_file=None):
    """Runs a shell command and returns the result."""
    cwd_str = str(cwd) if cwd else os.getcwd()
    cmd_str = " ".join(command)
    
    if log_file:
        log_file.write(f"[{datetime.now().isoformat()}] Executing: {cmd_str} in {cwd_str}\n")
        log_file.flush()
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Executing: {cmd_str}")

    try:
        if log_file:
            return subprocess.run(
                command,
                cwd=cwd,
                env=env or os.environ.copy(),
                check=check,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True
            )
        else:
            return subprocess.run(
                command,
                cwd=cwd,
                env=env or os.environ.copy(),
                check=check,
                text=True
            )
    except subprocess.CalledProcessError as e:
        msg = f"❌ Error executing command: {cmd_str}\nReturn code: {e.returncode}"
        if log_file:
            log_file.write(f"[{datetime.now().isoformat()}] {msg}\n")
            log_file.flush()
        else:
            print(msg)
        if check:
            raise e
        return None

def build_docker_image(name, path, image_url, root_dir, use_docker, log_path):
    """Worker function for building a single Docker image."""
    full_path = root_dir / path
    with open(log_path, "w") as f:
        dockerfile_path = full_path / "Dockerfile"
        if not dockerfile_path.exists():
            f.write(f"Error: Dockerfile not found at {dockerfile_path}\n")
            raise FileNotFoundError(f"Dockerfile not found for {name}")

        if use_docker:
            f.write(f"Building {name} with docker (from project root)...\n")
            run_command([
                "docker", "build", 
                "-t", image_url, 
                "-f", str(dockerfile_path),
                "."
            ], cwd=root_dir, log_file=f)
            f.write(f"Pushing {name}...\n")
            run_command(["docker", "push", image_url], log_file=f)
        else:
            f.write(f"Building {name} with gcloud builds submit (from project root)...\n")
            # Build from root context to handle uv workspace dependencies correctly
            temp_dockerfile = root_dir / f"Dockerfile.{name}"
            shutil.copy2(dockerfile_path, temp_dockerfile)
            try:
                run_command([
                    "gcloud", "builds", "submit", 
                    "--tag", image_url, 
                    "--dockerfile", str(temp_dockerfile), # gcloud supports --dockerfile now usually
                    "."
                ], cwd=root_dir, log_file=f)
            except Exception as e:
                # Fallback if --dockerfile isn't supported or fails
                f.write(f"Retrying with direct Dockerfile copy to root...\n")
                actual_temp = root_dir / "Dockerfile"
                shutil.copy2(dockerfile_path, actual_temp)
                try:
                    run_command([
                        "gcloud", "builds", "submit", 
                        "--tag", image_url, 
                        "."
                    ], cwd=root_dir, log_file=f)
                finally:
                    if actual_temp.exists(): os.remove(actual_temp)
            finally:
                if temp_dockerfile.exists():
                    os.remove(temp_dockerfile)
    return name

def package_traffic_generator(traffic_gen_dir, zip_path_base, project_id, region, log_path):
    """Worker function for packaging and uploading traffic generator."""
    with open(log_path, "w") as f:
        f.write(f"Packaging Traffic Generator from {traffic_gen_dir}...\n")
        shutil.make_archive(str(zip_path_base), "zip", str(traffic_gen_dir))
        
        zip_path = Path(f"{zip_path_base}.zip")
        bucket_name = f"{project_id}-deploy-artifacts"
        gcs_path = f"gs://{bucket_name}/traffic_generator_source.zip"
        
        f.write(f"Creating bucket {bucket_name} if needed...\n")
        subprocess.run(["gsutil", "mb", "-l", region, f"gs://{bucket_name}"], check=False, stdout=f, stderr=subprocess.STDOUT)
        
        f.write(f"Uploading {zip_path} to {gcs_path}...\n")
        run_command(["gsutil", "cp", str(zip_path), gcs_path], log_file=f)
    return gcs_path

def deploy_agent_engine_task(root_dir, project_id, region, log_path):
    """Worker function for deploying Agent Engine."""
    with open(log_path, "w") as f:
        f.write("Deploying Agent Engine...\n")
        agent_deploy_command = [
            "uv", "run", "deploy-agent-engine", "--create",
            "--project_id", project_id,
            "--location", region,
            "--bucket", f"{project_id}-deploy-artifacts"
        ]
        run_command(agent_deploy_command, cwd=root_dir, log_file=f)
    return True

def ensure_terraform_imports(terraform_dir, project_id, log_file=None):
    """Checks for already existing resources and imports them into state."""
    msg = "🔍 Checking for existing resources to import into Terraform state..."
    if log_file: log_file.write(f"{msg}\n")
    print(msg)
    
    # Get current state list
    try:
        result = subprocess.run(["terraform", "state", "list"], cwd=terraform_dir, capture_output=True, text=True)
        state_list = result.stdout.splitlines() if result.returncode == 0 else []
    except Exception:
        state_list = []
    
    # Known fixed-name resources that often cause 409 errors
    sas = {
        "google_service_account.flight_specialist": "flight-specialist",
        "google_service_account.weather_specialist": "weather-specialist",
        "google_service_account.profile_mcp": "profile-mcp",
        "google_service_account.test_runner": "travel-test-runner",
        "google_service_account.inventory_mcp_gsa": "inventory-mcp-gsa",
    }
    
    for tf_name, sa_id in sas.items():
        if tf_name not in state_list:
            sa_email = f"{sa_id}@{project_id}.iam.gserviceaccount.com"
            # Using full resource ID for import
            full_id = f"projects/{project_id}/serviceAccounts/{sa_email}"
            
            # check if exists in GCP
            check = subprocess.run(["gcloud", "iam", "service-accounts", "describe", sa_email, "--project", project_id], capture_output=True)
            if check.returncode == 0:
                print(f"  📥 Importing {tf_name} ({sa_email})...")
                # We don't want to fail if import fails (e.g. if it's already in state but we missed it)
                subprocess.run(["terraform", "import", tf_name, full_id], cwd=terraform_dir, capture_output=True)

def main():
    """Builds images, packages resources, and deploys using Terraform in parallel."""
    root_dir = Path(__file__).parent.parent.absolute()
    terraform_dir = root_dir / "terraform"
    logs_dir = root_dir / "logs" / "deploy"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
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
    cluster_name = env.get("CLUSTER_NAME", "summitt-cluster") # Using specific cluster name if found

    if not project_id:
        print("❌ Error: PROJECT_ID or GOOGLE_CLOUD_PROJECT must be set in .env")
        sys.exit(1)

    print(f"🚀 Deploying to project: {project_id} in region: {region}")
    print(f"📄 Logs will be written to: {logs_dir}")

    registry_prefix = f"gcr.io/{project_id}"
    components = {
        "flight-specialist": "agents/FlightSpecialist",
        "weather-specialist": "agents/WeatherSpecialist",
        "hotel-specialist": "agents/HotelSpecialist",
        "car-rental-specialist": "agents/CarRentalSpecialist",
        "profile-mcp": "mcp_servers/Profile_MCP",
        "inventory-mcp": "mcp_servers/Inventory_MCP",
    }

    # Docker status check
    use_docker = False
    if shutil.which("docker"):
        try:
            if subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0:
                use_docker = True
        except: pass
    
    if not use_docker:
        print("⚠️ Docker daemon unreachable, falling back to 'gcloud builds'...")

    image_urls = {}
    for name in components:
        image_urls[name.replace("-", "_") + "_image"] = f"{registry_prefix}/{name}:latest"

    # Start parallel tasks
    futures = []
    print("\n🏗️  Starting parallel deployment tasks...")
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        # 1. Docker Builds
        for name, path in components.items():
            image_url = image_urls[name.replace("-", "_") + "_image"]
            log_path = logs_dir / f"build_{name}.log"
            futures.append(executor.submit(build_docker_image, name, path, image_url, root_dir, use_docker, log_path))

        # 2. Traffic Generator
        traffic_gen_dir = root_dir / "traffic_generator"
        if traffic_gen_dir.exists():
            log_path = logs_dir / "package_traffic_generator.log"
            futures.append(executor.submit(package_traffic_generator, traffic_gen_dir, root_dir / "traffic_generator_source", project_id, region, log_path))
        else:
            image_urls["traffic_generator_source_zip"] = "gs://mock/source.zip"

        # 3. Agent Engine
        log_path = logs_dir / "deploy_agent_engine.log"
        futures.append(executor.submit(deploy_agent_engine_task, root_dir, project_id, region, log_path))

        # Wait for all to complete
        print("⏳ Waiting for builds and packaging to complete...")
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result()
                if isinstance(result, str) and result.startswith("gs://"):
                    image_urls["traffic_generator_source_zip"] = result
                elif isinstance(result, str):
                    print(f"  ✅ Built image for {result}")
                else:
                    print(f"  ✅ Parallel task completed")
            except Exception as e:
                print(f"  ❌ Task failed: {e}")
                print("Exiting due to failure.")
                sys.exit(1)

    # 4. Terraform Deploy
    print("\n🏗️  Proceeding to Terraform...")
    
    run_command(["terraform", "init"], cwd=terraform_dir)
    
    # Automatically handle 'already exists' for SAs
    ensure_terraform_imports(terraform_dir, project_id)
    
    tf_vars = [
        "-var", f"project_id={project_id}",
        "-var", f"region={region}",
        "-var", f"cluster_name={cluster_name}",
    ]
    for key, value in image_urls.items():
        tf_vars.extend(["-var", f"{key}={value}"])

    print("🚀 Applying Terraform (with parallelism=20)...")
    run_command(["terraform", "apply", "-auto-approve", "-parallelism=20"] + tf_vars, cwd=terraform_dir)

    print("\n✅ Deployment Complete!")

if __name__ == "__main__":
    main()
