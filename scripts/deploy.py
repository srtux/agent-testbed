import os
import sys
import subprocess
import shutil
import json
import concurrent.futures
from pathlib import Path
from datetime import datetime
import argparse
from dotenv import dotenv_values


def run_command(command, cwd=None, env=None, check=True, log_file=None, capture_output=False):
    """Runs a shell command and returns the result."""
    cwd_str = str(cwd) if cwd else os.getcwd()
    cmd_str = " ".join(command)

    if log_file:
        log_file.write(f"[{datetime.now().isoformat()}] Executing: {cmd_str} in {cwd_str}\n")
        log_file.flush()
    else:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Executing: {cmd_str}")

    try:
        if capture_output:
            return subprocess.run(
                command,
                cwd=cwd,
                env=env or os.environ.copy(),
                check=check,
                capture_output=True,
                text=True
            )
        elif log_file:
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
        msg = f"Error executing command: {cmd_str}\nReturn code: {e.returncode}"
        if log_file:
            log_file.write(f"[{datetime.now().isoformat()}] {msg}\n")
            log_file.flush()
        else:
            print(msg)
        if check:
            raise e
        return None


def build_docker_image(name, path, image_url, root_dir, use_docker, log_path, project_id=None):
    """Worker function for building a single Docker image."""
    full_path = root_dir / path
    with open(log_path, "w") as f:
        dockerfile_path = full_path / "Dockerfile"
        if not dockerfile_path.exists():
            f.write(f"Error: Dockerfile not found at {dockerfile_path}\n")
            raise FileNotFoundError(f"Dockerfile not found for {name}")

        if use_docker:
            f.write(f"🐳 Building {name} with docker (from project root)...\n")
            run_command([
                "docker", "build",
                "-t", image_url,
                "-f", str(dockerfile_path),
                "."
            ], cwd=root_dir, log_file=f)
            f.write(f"📤 Pushing {name} to {image_url}...\n")
            run_command(["docker", "push", image_url], log_file=f)
        else:
            f.write(f"☁️ Building {name} with gcloud builds submit (from project root)...\n")
            # Build from root context to handle uv workspace dependencies correctly
            temp_dockerfile = root_dir / f"Dockerfile.{name}"
            shutil.copy2(dockerfile_path, temp_dockerfile)
            
            # Create a temporary cloudbuild.yaml to avoid --dockerfile argument issues
            # and allow safe parallel builds.
            cloudbuild_content = f"""
steps:
- name: 'gcr.io/cloud-builders/docker'
  args: ['build', '-t', '{image_url}', '-f', 'Dockerfile.{name}', '.']
images:
- '{image_url}'
"""
            cloudbuild_path = root_dir / f"cloudbuild-{name}.yaml"
            with open(cloudbuild_path, "w") as cb:
                cb.write(cloudbuild_content.strip() + "\n")

            try:
                cmd = [
                    "gcloud", "builds", "submit",
                    "--config", str(cloudbuild_path),
                ]
                if project_id:
                    cmd.extend(["--project", project_id])
                cmd.append(".")
                
                run_command(cmd, cwd=root_dir, log_file=f)
            finally:
                if cloudbuild_path.exists():
                    os.remove(cloudbuild_path)
                if temp_dockerfile.exists():
                    os.remove(temp_dockerfile)
    return name


def package_traffic_generator(traffic_gen_dir, zip_path_base, project_id, region, log_path, bucket_name):
    """Worker function for packaging and uploading traffic generator."""
    with open(log_path, "w") as f:
        f.write(f"📦 Packaging Traffic Generator from {traffic_gen_dir}...\n")
        shutil.make_archive(str(zip_path_base), "zip", str(traffic_gen_dir))

        zip_path = Path(f"{zip_path_base}.zip")
        gcs_path = f"gs://{bucket_name}/traffic_generator_source.zip"

        f.write(f"🪣 Creating bucket {bucket_name} if needed...\n")
        cmd_create = ["gcloud", "storage", "buckets", "create", f"gs://{bucket_name}", "--location", region]
        if project_id:
            cmd_create.extend(["--project", project_id])
        subprocess.run(cmd_create, check=False, stdout=f, stderr=subprocess.STDOUT)

        f.write(f"📤 Uploading {zip_path} to {gcs_path}...\n")
        cmd_cp = ["gcloud", "storage", "cp", str(zip_path), gcs_path]
        if project_id:
            cmd_cp.extend(["--project", project_id])
        run_command(cmd_cp, log_file=f)
    return gcs_path


def ensure_terraform_imports(terraform_dir, project_id, region, tf_vars, bucket_name, log_file=None):
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

    # 1. Service Accounts
    sas = {
        "google_service_account.flight_specialist": "flight-specialist",
        "google_service_account.weather_specialist": "weather-specialist",
        "google_service_account.profile_mcp": "profile-mcp",
        "google_service_account.test_runner": "travel-test-runner",
        "google_service_account.inventory_mcp_gsa": "inventory-mcp-gsa",
        "google_service_account.gke_agents_gsa": "gke-agents-gsa",
    }

    for tf_name, sa_id in sas.items():
        if tf_name not in state_list:
            sa_email = f"{sa_id}@{project_id}.iam.gserviceaccount.com"
            full_id = f"projects/{project_id}/serviceAccounts/{sa_email}"

            check = subprocess.run(
                ["gcloud", "iam", "service-accounts", "describe", sa_email, "--project", project_id],
                capture_output=True
            )
            if check.returncode == 0:
                print(f"  📥 Importing {tf_name} ({sa_email})...")
                subprocess.run(["terraform", "import"] + tf_vars + [tf_name, full_id], cwd=terraform_dir, capture_output=True)

    # 2. Generic Resources (e.g., Network Attachments)
    generic_resources = {
        "google_compute_network_attachment.reasoning_engine": f"{project_id}/{region}/reasoning-engine-attachment"
    }

    for tf_name, full_id in generic_resources.items():
        if tf_name not in state_list:
            res_name = full_id.split("/")[-1]
            # Check if network attachment exists with describe
            check = subprocess.run(
                ["gcloud", "compute", "network-attachments", "describe", res_name, "--region", region, "--project", project_id],
                capture_output=True
            )
            if check.returncode == 0:
                print(f"  📥 Importing {tf_name} ({res_name})...")
                subprocess.run(["terraform", "import"] + tf_vars + [tf_name, full_id], cwd=terraform_dir, capture_output=True)

    # 3. GCS Bucket
    if "google_storage_bucket.deploy_artifacts" not in state_list:
        check = subprocess.run(
            ["gcloud", "storage", "buckets", "describe", f"gs://{bucket_name}", "--project", project_id],
            capture_output=True
        )
        if check.returncode == 0:
            print(f"  📥 Importing google_storage_bucket.deploy_artifacts ({bucket_name})...")
            subprocess.run(["terraform", "import"] + tf_vars + ["google_storage_bucket.deploy_artifacts", bucket_name], cwd=terraform_dir, capture_output=True)


def get_terraform_output(terraform_dir, output_name):
    """Reads a single output value from Terraform state."""
    result = subprocess.run(
        ["terraform", "output", "-raw", output_name],
        cwd=terraform_dir,
        capture_output=True,
        text=True
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def deploy_agent_engine_task(root_dir, project_id, region, custom_domain, log_path, bucket_name):
    """Deploys Agent Engine agents. Returns dict of agent outputs from JSON file."""
    terraform_dir = root_dir / "terraform"
    psc_attachment = get_terraform_output(terraform_dir, "psc_network_attachment")
    vpc_name = get_terraform_output(terraform_dir, "vpc_name")
    vpc_project = get_terraform_output(terraform_dir, "vpc_project_id")

    with open(log_path, "w") as f:
        f.write("🤖 Deploying Agent Engine...\n")
        agent_deploy_command = [
            "uv", "run", "deploy-agent-engine", "--create",
            "--project_id", project_id,
            "--location", region,
            "--bucket", bucket_name,
        ]
        if custom_domain:
            agent_deploy_command.extend(["--custom_domain", custom_domain])
        
        if psc_attachment:
            agent_deploy_command.extend(["--psc_network_attachment", psc_attachment])
        if vpc_name:
            agent_deploy_command.extend(["--vpc_name", vpc_name])
        if vpc_project:
            agent_deploy_command.extend(["--vpc_project_id", vpc_project])

        run_command(agent_deploy_command, cwd=root_dir, log_file=f)

    # Read the outputs JSON written by deploy_agent_engine.py
    outputs_path = root_dir / "agent_engine_outputs.json"
    if outputs_path.exists():
        with open(outputs_path) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(description="Deploy the agent testbed.")
    parser.add_argument("--skip-build", action="store_true", help="Skip Phase 1 (Docker builds)")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3, 4], help="Run only specific phase and subsequent phases")
    args = parser.parse_args()

    root_dir = Path(__file__).parent.parent.absolute()
    terraform_dir = root_dir / "terraform"
    logs_dir = root_dir / "logs" / "deploy"
    logs_dir.mkdir(parents=True, exist_ok=True)

    # Load environment variables from .env (using dotenv for proper quote/export handling)
    env = os.environ.copy()
    env_file = root_dir / ".env"
    if env_file.exists():
        dotenv_vars = dotenv_values(env_file)
        env.update({k: v for k, v in dotenv_vars.items() if v is not None})

    project_id = env.get("PROJECT_ID", env.get("GOOGLE_CLOUD_PROJECT"))
    region = env.get("REGION", env.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    cluster_name = env.get("CLUSTER_NAME", "default-cluster")
    custom_domain = env.get("CUSTOM_DOMAIN", "")

    if not project_id:
        print("Error: PROJECT_ID or GOOGLE_CLOUD_PROJECT must be set in .env")
        sys.exit(1)

    mode = "custom_domain" if custom_domain else "direct"
    print(f"Deploying to project: {project_id} in region: {region}")
    print(f"Mode: {mode}" + (f" (domain: {custom_domain})" if custom_domain else " (Cloud Run native URLs + GKE LoadBalancer IPs)"))
    print(f"Logs will be written to: {logs_dir}")

    registry_prefix = f"{region}-docker.pkg.dev/{project_id}/testbed"
    # Get project number to make bucket name unique and avoid name collisions
    try:
        result = subprocess.run(
            ["gcloud", "projects", "describe", project_id, "--format=value(projectNumber)"],
            capture_output=True, text=True, check=True
        )
        project_number = result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"❌ Error fetching project number: {e}")
        sys.exit(1)

    bucket_name = f"{project_id}-deploy-artifacts-{project_number}-testbed"
    print(f"🪣 Using deployment artifacts bucket: {bucket_name}")

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
        except Exception:
            pass

    if not use_docker:
        print("⚠️  Docker daemon unreachable, falling back to 'gcloud builds'...")

    image_urls = {}
    for name in components:
        image_urls[name.replace("-", "_") + "_image"] = f"{registry_prefix}/{name}:latest"

    # =========================================================================
    # Phase 1: Build images + package traffic generator (parallel)
    # =========================================================================
    if not args.skip_build and (not args.phase or args.phase <= 1):
        build_futures = []
        print("\n[Phase 1] 🛠️  Starting parallel build tasks...")

        num_workers = 10  # Enabled parallel builds for gcloud builds as well
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_workers) as executor:
            for name, path in components.items():
                image_url = image_urls[name.replace("-", "_") + "_image"]
                log_path = logs_dir / f"build_{name}.log"
                build_futures.append(
                    executor.submit(build_docker_image, name, path, image_url, root_dir, use_docker, log_path, project_id)
                )

            traffic_gen_dir = root_dir / "traffic_generator"
            if traffic_gen_dir.exists():
                log_path = logs_dir / "package_traffic_generator.log"
                build_futures.append(
                    executor.submit(package_traffic_generator, traffic_gen_dir, root_dir / "traffic_generator_source", project_id, region, log_path, bucket_name)
                )
            else:
                image_urls["traffic_generator_source_zip"] = "gs://mock/source.zip"

            print("⏳ Waiting for builds and packaging to complete...")
            for future in concurrent.futures.as_completed(build_futures):
                try:
                    result = future.result()
                    if isinstance(result, str) and result.startswith("gs://"):
                        # Terraform storage_source expects just the object name, not the full gs:// URI
                        image_urls["traffic_generator_source_zip"] = result.split("/")[-1]
                    elif isinstance(result, str):
                        print(f"  ✅ Built image for {result}")
                    else:
                        print(f"  ✅ Parallel task completed")
                except Exception as e:
                    print(f"  ❌ Task failed: {e}")
                    print("Exiting due to build failure.")
                    sys.exit(1)
    else:
        print("\n[Phase 1] ⏭️  Skipping build phase...")
        image_urls["traffic_generator_source_zip"] = "traffic_generator_source.zip"

    # =========================================================================
    # Phase 2: Terraform (provisions Cloud Run, GKE, LBs, Cloud Functions)
    # =========================================================================
    if not args.phase or args.phase <= 2:
        print("\n[Phase 2] 🏗️  Running Terraform...")

        tf_state_bucket = env.get("TF_STATE_BUCKET", f"{project_id}-tf-state")
        run_command(
            ["terraform", "init", "-upgrade", "-reconfigure", f"-backend-config=bucket={tf_state_bucket}"],
            cwd=terraform_dir
        )

        tf_vars = [
            "-var", f"project_id={project_id}",
            "-var", f"region={region}",
            "-var", f"cluster_name={cluster_name}",
            "-var", f"custom_domain={custom_domain}",
            "-var", f"deploy_timestamp={datetime.now().strftime('%Y%m%dt%H%M%S')}",
            "-var", f"deploy_bucket_name={bucket_name}",
        ]
        for key, value in image_urls.items():
            tf_vars.extend(["-var", f"{key}={value}"])

        # Automatically handle 'already exists' for SAs and Network Attachments
        ensure_terraform_imports(terraform_dir, project_id, region, tf_vars, bucket_name)

        print("🚀 Applying Terraform (with parallelism=20)...")
        apphub_path = Path(terraform_dir) / "apphub.tf"
        apphub_disabled = Path(terraform_dir) / "apphub.tf.disabled"
        
        if apphub_path.exists():
            print("⏳ Temporarily disabling apphub.tf for first apply...")
            os.rename(apphub_path, apphub_disabled)
            
        try:
            run_command(["terraform", "apply", "-auto-approve", "-parallelism=20"] + tf_vars, cwd=terraform_dir)
        finally:
            if apphub_disabled.exists():
                print("🔄 Restoring apphub.tf...")
                os.rename(apphub_disabled, apphub_path)

        # Read and display service URLs from Terraform outputs
        service_url_names = ["flight_specialist_url", "weather_specialist_url", "profile_mcp_url",
                             "hotel_specialist_url", "car_rental_url", "inventory_mcp_url",
                             "flight_specialist_audience", "weather_specialist_audience", "profile_mcp_audience"]
        service_urls = {}
        print("\n  Service URLs:")
        for output_name in service_url_names:
            url = get_terraform_output(terraform_dir, output_name)
            if url:
                service_urls[output_name] = url
                print(f"    {output_name}: {url}")

        # Write service URLs for Agent Engine deploy to consume
        urls_path = root_dir / "terraform_service_urls.json"
        with open(urls_path, "w") as f:
            json.dump(service_urls, f, indent=2)

        if custom_domain:
            cloud_run_lb_ip = get_terraform_output(terraform_dir, "cloud_run_lb_ip")
            gke_lb_ip = get_terraform_output(terraform_dir, "gke_lb_ip")
            print(f"\n  Configure DNS A records:")
            print(f"    flight-specialist.{custom_domain} -> {cloud_run_lb_ip}")
            print(f"    weather-specialist.{custom_domain} -> {cloud_run_lb_ip}")
            print(f"    profile-mcp.{custom_domain}        -> {cloud_run_lb_ip}")
            print(f"    hotel-specialist.{custom_domain}    -> {gke_lb_ip}")
            print(f"    car-rental.{custom_domain}          -> {gke_lb_ip}")
            print(f"    inventory-mcp.{custom_domain}       -> {gke_lb_ip}")

    # =========================================================================
    # Phase 3: Agent Engine (runs AFTER Terraform so URLs are known)
    # =========================================================================
    if not args.phase or args.phase <= 3:
        print("\n[Phase 3] Deploying Agent Engine...")

        log_path = logs_dir / "deploy_agent_engine.log"
        agent_outputs = deploy_agent_engine_task(root_dir, project_id, region, custom_domain, log_path, bucket_name)

        # The Agent Engine resource names can be used to construct the HTTP endpoint URLs
        # Format: projects/{project}/locations/{location}/reasoningEngines/{id}
        # The actual invocation URLs depend on Agent Engine API surface
        root_router_resource = agent_outputs.get("RootRouter", "")
        booking_resource = agent_outputs.get("BookingOrchestrator", "")

        if root_router_resource:
            print(f"  RootRouter resource: {root_router_resource}")
        if booking_resource:
            print(f"  BookingOrchestrator resource: {booking_resource}")

        # =========================================================================
        # Phase 4: Re-apply Terraform with Agent Engine URLs
        # =========================================================================
        if root_router_resource or booking_resource:
            print("\n[Phase 4] Re-applying Terraform with Agent Engine URLs...")

            # Note: We need tf_vars here. If we skipped Phase 2, we need to reconstruct it.
            # For simplicity, we assume if we are running Phase 3 or 4, we have the variables or we just ran Phase 2.
            # Reconstruct tf_vars if needed
            registry_prefix = f"{region}-docker.pkg.dev/{project_id}/testbed"
            components = {
                "flight-specialist": "agents/FlightSpecialist",
                "weather-specialist": "agents/WeatherSpecialist",
                "hotel-specialist": "agents/HotelSpecialist",
                "car-rental-specialist": "agents/CarRentalSpecialist",
                "profile-mcp": "mcp_servers/Profile_MCP",
                "inventory-mcp": "mcp_servers/Inventory_MCP",
            }
            image_urls = {}
            for name in components:
                image_urls[name.replace("-", "_") + "_image"] = f"{registry_prefix}/{name}:latest"
            image_urls["traffic_generator_source_zip"] = "traffic_generator_source.zip"

            tf_vars = [
                "-var", f"project_id={project_id}",
                "-var", f"region={region}",
                "-var", f"cluster_name={cluster_name}",
                "-var", f"custom_domain={custom_domain}",
                "-var", f"deploy_timestamp={datetime.now().strftime('%Y%m%dt%H%M%S')}",
                "-var", f"deploy_bucket_name={bucket_name}",
            ]
            for key, value in image_urls.items():
                tf_vars.extend(["-var", f"{key}={value}"])

            tf_vars_phase4 = tf_vars.copy()
            if root_router_resource:
                root_router_url_full = f"https://{region}-aiplatform.googleapis.com/v1/{root_router_resource}:query"
                tf_vars_phase4.extend(["-var", f"root_router_url={root_router_url_full}"])
            if booking_resource:
                booking_url_full = f"https://{region}-aiplatform.googleapis.com/v1/{booking_resource}:query"
                tf_vars_phase4.extend(["-var", f"booking_orchestrator_url={booking_url_full}"])


            run_command(
                ["terraform", "apply", "-auto-approve", "-parallelism=20"] + tf_vars_phase4,
                cwd=terraform_dir
            )
            print("  Terraform re-applied with Agent Engine URLs.")
        else:
            print("\n  ⚠️  Warning: No Agent Engine URLs captured. Traffic generator and WeatherSpecialist")
            print("  will not have Agent Engine URLs configured. Re-run with --root_router_url manually.")

    # =========================================================================
    # Phase 5: Post-deploy health checks
    # =========================================================================
    print("\n[Phase 5] 🏥 Running post-deploy health checks...")

    # Read service URLs from the JSON bridge file (written by Phase 2)
    urls_path = root_dir / "terraform_service_urls.json"
    if urls_path.exists():
        with open(urls_path) as f:
            health_urls = json.load(f)

        import urllib.request
        import urllib.error
        all_healthy = True
        for svc_name, svc_url in health_urls.items():
            health_url = svc_url.rstrip("/") + "/health"
            try:
                req = urllib.request.Request(health_url, method="GET")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        print(f"  ✅ {svc_name}: healthy")
                    else:
                        print(f"  ⚠️  {svc_name}: returned {resp.status}")
                        all_healthy = False
            except Exception as e:
                print(f"  ❌ {svc_name}: {e}")
                all_healthy = False

        if not all_healthy:
            print("\n⚠️  Some services are not healthy. Check logs above.")
    else:
        print("  ⏭️  No terraform_service_urls.json found, skipping health checks.")

    print("\n✅ Deployment Complete!")


if __name__ == "__main__":
    main()
