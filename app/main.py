from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from sync import Sync
from sync.common import Audio, Video, GenerationOptions
from sync.core.api_error import ApiError
import os, uuid, time, requests, cloudinary, cloudinary.uploader
from tqdm import tqdm
from dotenv import load_dotenv

# ------------------- Load Environment -------------------
load_dotenv()

app = FastAPI(title="Sync.so Lip-Sync API")

# Sync API Key
API_KEY = os.getenv("SYNC_API_KEY")
if not API_KEY:
    raise RuntimeError("Missing SYNC_API_KEY in environment variables")

# Initialize Sync client
client = Sync(base_url="https://api.sync.so", api_key=API_KEY).generations

# Cloudinary Setup
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
if not CLOUDINARY_URL:
    raise RuntimeError("Missing CLOUDINARY_URL in environment variables")

cloudinary.config(cloudinary_url=CLOUDINARY_URL)

# Local folder (for temp save)
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Predefined videos
PREDEFINED_VIDEOS = {
    "video1": "https://drive.google.com/uc?export=download&id=1zEQnsgkUrFHGZDRzFPmxYXm0qKNREDFI"
}

# ------------------- Main Endpoint -------------------
@app.post("/generate-lipsync/")
async def generate_lipsync(
    audio: UploadFile = File(...),
    video_choice: str = Query("video1", description="Choose predefined video")
):
    if video_choice not in PREDEFINED_VIDEOS:
        raise HTTPException(status_code=400, detail="Invalid video choice")

    video_url = PREDEFINED_VIDEOS[video_choice]
    audio_path = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_{audio.filename}")

    try:
        # Save audio locally
        with open(audio_path, "wb") as f:
            f.write(await audio.read())

        # Upload audio to Cloudinary (get public URL)
        upload_result = cloudinary.uploader.upload(audio_path, resource_type="video")
        public_audio_url = upload_result["secure_url"]

        print(f"🎵 Uploaded audio to Cloudinary: {public_audio_url}")

        # Start Sync.so generation
        response = client.create(
            input=[Video(url=video_url), Audio(url=public_audio_url)],
            model="lipsync-2",
            options=GenerationOptions(sync_mode="cut_off")
        )

        job_id = response.id
        status = "PENDING"
        progress_bar = tqdm(total=100, desc="Processing", position=0)

        while status not in ["COMPLETED", "FAILED"]:
            time.sleep(5)
            generation = client.get(job_id)
            status = generation.status
            progress_bar.update(5)
            progress_bar.set_postfix_str(f"Status: {status}")

        progress_bar.close()

        if status == "COMPLETED":
            output_file = os.path.join(UPLOAD_FOLDER, f"{uuid.uuid4().hex}_lipsync.mp4")
            r = requests.get(generation.output_url, stream=True)
            with open(output_file, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

            return FileResponse(
                path=output_file,
                filename="lipsync_video.mp4",
                media_type="video/mp4"
            )
        else:
            raise HTTPException(status_code=500, detail="Generation failed")

    except ApiError as e:
        raise HTTPException(status_code=e.status_code, detail=e.body)

    finally:
        if os.path.exists(audio_path):
            os.remove(audio_path)
