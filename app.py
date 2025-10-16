from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from contextlib import asynccontextmanager
import httpx
import asyncio

from db import init_db, get_db
from models import Prediction

# HF Space API endpoint
HF_SPACE_URL = "https://iYami-cloud.hf.space"
PREDICT_ENDPOINT = f"{HF_SPACE_URL}/api/predict"

print(f"📡 HF Space endpoint: {HF_SPACE_URL}")


# Lifespan handler for startup/shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Starting CIFAR-10 API wrapper...")
    try:
        init_db()
        print("✅ Database connected")
    except Exception as e:
        print(f"⚠️ Database initialization failed: {e}")
        print("   API will still run, but predictions won't be logged")

    # Test HF Space connection
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{HF_SPACE_URL}/info/")
            print(f"✅ HF Space reachable")
    except Exception as e:
        print(f"⚠️ Warning: Could not reach HF Space: {e}")

    print("✅ API ready!")
    yield

    # Shutdown
    print("👋 Shutting down API...")


# FastAPI app
app = FastAPI(
    title="CIFAR-10 Classifier API Wrapper",
    description="FastAPI wrapper that calls HF Space for inference and logs to PostgreSQL",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/", tags=["Health"])
def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "message": "CIFAR-10 API wrapper - forwards requests to HF Space",
        "hf_space": HF_SPACE_URL,
        "docs": "/docs"
    }


@app.get("/health", tags=["Health"])
def health():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.post("/predict", tags=["Inference"])
async def predict(
        file: UploadFile = File(..., description="Image file to classify"),
        db: Session = Depends(get_db)
):
    """
    Classify an image using the HF Space model.

    This endpoint:
    1. Receives an image from the client
    2. Forwards it to the HF Space for inference
    3. Logs the prediction and metadata to PostgreSQL
    4. Returns the result to the client

    Returns:
    - prediction: The top predicted class
    - probabilities: Probability distribution across all 10 classes
    - filename: The uploaded filename
    - inference_source: "hugging_face_space"
    """
    try:
        # Validate file
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")

        print(f"📥 Received image: {file.filename}")

        # 🚀 Forward to HF Space for inference
        print(f"📤 Sending to HF Space: {PREDICT_ENDPOINT}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Read file content
            content = await file.read()

            # Create multipart form data
            files = {
                'file': (file.filename, content, file.content_type)
            }

            # Call HF Space
            response = await client.post(PREDICT_ENDPOINT, files=files)
            response.raise_for_status()

            result = response.json()
            print(f"✅ HF Space response received")

        # Extract prediction data
        prediction = result.get("prediction")
        probabilities = result.get("probabilities", {})
        confidence = result.get("confidence", 0.0)

        # 💾 Log to PostgreSQL (if available)
        if db is not None:
            try:
                pred_entry = Prediction(
                    filename=file.filename,
                    prediction=prediction,
                    probabilities=str(probabilities),
                    confidence=confidence
                )
                db.add(pred_entry)
                db.commit()
                print(f"✅ Logged prediction to database")
            except Exception as db_err:
                print(f"⚠️ Failed to log to database: {db_err}")
                if db:
                    db.rollback()

        return {
            "filename": file.filename,
            "prediction": prediction,
            "confidence": confidence,
            "probabilities": probabilities,
            "inference_source": "hugging_face_space"
        }

    except httpx.HTTPError as e:
        print(f"❌ HF Space error: {e}")
        return JSONResponse(
            content={"error": f"HF Space inference failed: {str(e)}"},
            status_code=502
        )
    except Exception as e:
        print(f"❌ Error: {e}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )