import os
import traceback
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.services.extractor import extractor_service
from app.services.llm_validator import llm_validator

app = FastAPI(title="BluePace Tech ATS API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ValidationRequest(BaseModel):
    resume_json: dict
    job_description: str

@app.post("/extract/", response_class=JSONResponse)
async def extract_document(file: UploadFile = File(...)):
    if file.content_type not in ["application/pdf", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"]:
        raise HTTPException(status_code=400, detail="Unsupported file type.")
    try:
        content = await file.read()
        structured_data = extractor_service.extract_to_json(content, file.filename)
        return {"filename": file.filename, "status": "success", "data": structured_data}
    except Exception as e:
        print("\n" + "="*60)
        traceback.print_exc()
        print("="*60 + "\n")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/validate/", response_class=JSONResponse)
async def validate_resume(request: ValidationRequest):
    try:
        result = llm_validator.validate_resume(request.resume_json, request.job_description)
        return {"status": "success", "validation": result}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/")
async def root():
    return {"message": "Welcome to the BluePace Tech ATS API."}