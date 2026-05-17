# LexGuard

Contract intelligence prototype (hackathon build). See `context.md` and `build.md` for the spec.

## Structure

- `frontend/` — React + Vite, deploys to Vercel
- `backend/` — FastAPI single-file app, deploys to Railway

## Local dev

Backend:
```
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Frontend:
```
cd frontend
npm install
npm run dev
```

The frontend reads `VITE_API_URL` (defaults to `http://localhost:8000`).
