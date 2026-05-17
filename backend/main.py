from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}


FAKE_ANALYSIS = {
    "doc_type": "employment",
    "overall_risk_score": 60,
    "red_flag_count": 2,
    "clauses": [
        {
            "id": 1,
            "category": "non_compete",
            "clause_text": "Employee shall not, for a period of twenty-four (24) months following termination, engage in any business that competes with the Company anywhere in the world.",
            "plain_english": "You can't work for any competitor anywhere on Earth for two years after you leave.",
            "severity": "red",
            "risk_reason": "The 24-month duration and global scope are unusually broad and likely to restrict future employment.",
        },
        {
            "id": 2,
            "category": "IP",
            "clause_text": "All inventions, ideas, and works conceived by Employee during the term of employment, whether or not related to Company business, shall be the sole property of the Company.",
            "plain_english": "Anything you create while employed — even personal side projects — becomes the company's property.",
            "severity": "red",
            "risk_reason": "Assigns ownership of work unrelated to the employer's business, which is overreaching and unenforceable in many jurisdictions.",
        },
        {
            "id": 3,
            "category": "termination",
            "clause_text": "Either party may terminate this Agreement with thirty (30) days written notice.",
            "plain_english": "Either you or the company can end the contract with 30 days' notice.",
            "severity": "green",
            "risk_reason": "Mutual and standard notice period; low risk to the signer.",
        },
    ],
}


@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    # Phase 0: ignore the file, return fake JSON in the frozen schema.
    await file.read()
    return FAKE_ANALYSIS


@app.post("/negotiate")
async def negotiate(body: dict):
    # Phase 0: stub. Real Gemini call lands in Phase 2.
    return {"reply": "I hear your concern, but this clause reflects standard practice across our industry."}
