# Service account imports use dynamic project_id via the deploy.py
# ensure_terraform_imports() function. These static import blocks are
# kept as documentation but should not be used directly — the deploy
# script handles idempotent imports at runtime to avoid hardcoding
# project IDs.
#
# If you need to import manually, run:
#   terraform import google_service_account.test_runner \
#     "projects/<YOUR_PROJECT_ID>/serviceAccounts/travel-test-runner@<YOUR_PROJECT_ID>.iam.gserviceaccount.com"
