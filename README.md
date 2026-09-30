# smartSolveTroubleGuide
Samsung Prism Hackathon Project["Smart Guided Troubleshooting Engine"]
Clone the repository → create the Python environment → install dependencies → start the FastAPI backend → install frontend dependencies → start the React frontend.

Backend:
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

Frontend (new terminal):
cd frontend
npm install
npm run dev

Open the Vite URL shown in the terminal (typically http://localhost:5173).

No external AI API key is required for the core troubleshooting pipeline. The application uses the included processed troubleshooting data and semantic retrieval pipeline.

Run backend tests with:
python -m pytest -q

Build the frontend with:
cd frontend
npm run build
