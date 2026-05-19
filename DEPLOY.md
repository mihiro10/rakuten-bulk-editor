# Deploy (Render)

This app is ready for public hosting on Render.

## 1) Push this folder to GitHub

Render deploys from a Git repository. Put this project in a GitHub repo first.

## 2) Create a new Render Web Service

- In Render dashboard, click **New +** -> **Blueprint** (recommended)
- Select your repo
- Render will read `render.yaml` automatically

If you use **Web Service** instead of Blueprint:

- Runtime: `Python`
- Build command: *(empty)*
- Start command: `streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true`

## 3) Deploy

Render will set `PORT` automatically. The app already binds to `0.0.0.0:$PORT`.

## Notes

- Uploaded CSVs are handled in-memory/temp files per request.
- Download tokens are stored in memory with TTL. Restarting the service clears them.
