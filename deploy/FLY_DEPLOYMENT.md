# Fly Deployment Notes

Deploy the frontend only after the backend Fly app is healthy so the built assets can point to the correct hostname.

## Order of Operations
1. Deploy the backend Fly app (for example `brain-buddy-backend`) and confirm `https://<backend-app>.fly.dev/api/health` responds.
2. Update `fly.frontend.toml` if your backend app name differs, so `VITE_API_BASE_URL` targets `https://<backend-app>.fly.dev/api`.
3. Deploy the frontend with the Fly config that references `frontend/Dockerfile`.

## Auth
- Auth is cookie-based. Sign up is invite-gated — mint an invite via
  `flyctl ssh console -a <backend-app> -C "python -m app.cli create-invite"` and share the code.
- The frontend proxies `/api/*` to the private backend, forwarding `Cookie` / `Set-Cookie` so the session round-trips correctly.
- See `docs/auth.md` for the full security model.

## Runtime Notes
- `force_https` is enabled in `fly.frontend.toml` and NGINX serves assets with hour-long caching for `/assets/` per `deploy/nginx/default.conf`.
- Update `primary_region` or autoscaling options in `fly.frontend.toml` as needed for your Fly organization.
