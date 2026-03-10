# Vertex AI Agent Engine deployments are currently orchestrated directly by the 
# deploy_all.py script rather than via native Terraform resources. 
# This is because the Vertex AI Reasoning Engines (ADK) rely on complex 
# local packaging (e.g., parsing uv dependencies and generating AdkApp bundles)
# which is difficult to represent purely natively in Terraform without 
# excessive null_resources and local-exec complexity that obscures the deployment.
