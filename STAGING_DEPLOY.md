# Masari Staging Deployment

This is a public experimental web deployment, not the production release.

Railway:
1. Deploy the `staging-web-v1` branch.
2. Attach one Volume to the web service at `/data`.
3. Generate a public domain in Networking.
4. Keep one replica / one Uvicorn worker while the staging scheduler runs in-process.

The app automatically uses:
`$RAILWAY_VOLUME_MOUNT_PATH/emploi_public`

Schedule (Africa/Casablanca):
- 05:30 full source refresh
- 10:30 quick refresh
- 14:30 quick refresh
- 18:30 quick refresh

The web process remains online while refresh runs. `maintenance/refresh.py` atomically
replaces the index only after successful validation.
