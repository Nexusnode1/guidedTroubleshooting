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

PPT PRESENTATION- https://drive.google.com/file/d/1ni0A_5i_XONhL3r4mK5ai6MbOpsyxMTa/view?usp=drive_link
VIDEO PRESENTATION- https://drive.google.com/file/d/1d9tQp6_i_HfoUqJe0kBjkfpNXeeOkSjk/view?usp=drive_link
Ai disclosure form- https://docs.google.com/document/d/1tH2YW8sYDmTy7M4Bg2pa7_usvhdS-3M9/edit?usp=drive_link&ouid=107818180219584564151&rtpof=true&sd=true
