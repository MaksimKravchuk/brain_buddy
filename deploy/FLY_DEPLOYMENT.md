# Fly Deployment Notes

Deploy the frontend only after the backend Fly app is healthy so the built assets can point to the correct hostname.

## Order of Operations
1. Deploy the backend Fly app (for example `brain-buddy-backend`) and confirm `https://<backend-app>.fly.dev/api/health` responds.
2. Update `fly.frontend.toml` if your backend app name differs, so `VITE_API_BASE_URL` targets `https://<backend-app>.fly.dev/api`.
3. Deploy the frontend with the Fly config that references `frontend/Dockerfile`.

## API Key Wiring
- Backend: `fly secrets set BRAIN_BUDDY_API_KEY=<your-key> BRAIN_BUDDY_API_KEY_HEADER=<header-name>` on the backend app.
- Frontend: `fly secrets set VITE_API_KEY=<your-key> VITE_API_KEY_HEADER=<header-name>` on the frontend app (only when the backend requires a key).
- Keep the header values in sync between apps so requests are authorized correctly.

## Runtime Notes
- `force_https` is enabled in `fly.frontend.toml` and NGINX serves assets with hour-long caching for `/assets/` per `deploy/nginx/default.conf`.
- Update `primary_region` or autoscaling options in `fly.frontend.toml` as needed for your Fly organization.
