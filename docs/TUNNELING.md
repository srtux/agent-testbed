# Secure Tunneling via Bastion Host

Since your microservices are locked down for internal VPC traffic (Cloud Run ingress or GKE internal IPs), you can use the newly deployed **Bastion Host** as a secure gateway from your local machine.

---

## 🚀 1. Establish the SOCKS5 Proxy Tunnel

Run the following command in a **separate terminal window** to establish a secure SOCKS5 proxy session over SSH:

```bash
gcloud compute ssh testbed-bastion \
    --tunnel-through-iap \
    --zone [BASTION_ZONE] \
    --project [PROJECT_ID] \
    -- -D 8888 -N
```
> [!TIP]
> You can find the exact command already formatted in your Terraform outputs as `bastion_ssh_command`.

*   `-D 8888`: Binds a local SOCKS5 proxy to port `8888`.
*   `-N`: Instructs SSH to not execute remote commands (just forward).
*   **Keep this window open** while you want to use the tunnel.

---

## 🛠️ 2. Route Local Traffic

### Using standard `curl`
To test endpoints, append `--proxy socks5h://localhost:8888`:

```bash
# Test internal Cloud Run url (resolves correctly inside VPC)
curl --proxy socks5h://localhost:8888 https://flight-specialist-[hash]-uc.a.run.app/health

# Test internal GKE IP
curl --proxy socks5h://localhost:8888 http://10.128.0.94/health
```
*(Use `socks5h://` so containing DNS resolution is also routed inside the VPC!)*

---

### Using Python (`httpx` or `requests`)

To make requests in scripts, install the SOCKS extension:

```bash
# For HTTPX (ADK uses httpx)
pip install "httpx[socks]"
```

Then use the proxy in your client setup:

```python
import httpx

# Configure to route all traffic through SOCKS5
proxies = {
    "all://": "socks5://localhost:8888"
}

with httpx.Client(proxies=proxies) as client:
    # Test Cloud Run Internal URL
    res = client.get("https://flight-specialist-[hash]-uc.a.run.app/health")
    print(res.json())
```

---

## 🧹 3. Troubleshooting
-   **Timeout on SSH**: Verify that the `testbed-allow-iap-ssh-to-bastion` firewall rule exists allowing traffic from `35.235.240.0/20` to tag `bastion`.
-   **Permission Denied**: Ensure you have the `roles/iap.tunnelResourceAccessor` and `roles/compute.viewer` IAM roles on your service account/identity.
