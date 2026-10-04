from __future__ import annotations

from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from io import BytesIO
import json
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from PIL import Image, ImageDraw, ImageOps

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
UPLOADS_DIR = STORAGE_DIR / "uploads"
GENERATED_DIR = STORAGE_DIR / "generated"
TMP_DIR = STORAGE_DIR / "tmp"
DB_PATH = STORAGE_DIR / "image_jobs.db"
MAX_FILE_SIZE = 8 * 1024 * 1024
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg"}
ALLOWED_CONTENT_TYPES = {"image/png", "image/jpeg"}
DEFAULT_HISTORY_LIMIT = 8
MAX_HISTORY_LIMIT = 20
DEFAULT_ALGORITHM = "baseline-inspector"
EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="image-worker")
DB_LOCK = Lock()

app = FastAPI(title="TradingAI Pro Image Service", version="0.1.0")


class RenderRequest(BaseModel):
    job_id: str | None = None
    analysis: dict[str, Any] | None = None
    input_path: str | None = None
    input_url: str | None = None
    algorithm: str | None = None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_storage() -> None:
    for directory in (STORAGE_DIR, UPLOADS_DIR, GENERATED_DIR, TMP_DIR):
        directory.mkdir(parents=True, exist_ok=True)

    with DB_LOCK:
        with closing(sqlite3.connect(DB_PATH)) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS image_jobs (
                    id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    input_path TEXT NOT NULL,
                    output_path TEXT,
                    result_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    finished_at TEXT
                )
                """
            )
            conn.commit()


@app.on_event("startup")
def startup() -> None:
    ensure_storage()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def insert_job(job_id: str, job_type: str, algorithm: str, input_path: str) -> None:
    now = utc_now_iso()
    with DB_LOCK:
        with closing(get_connection()) as conn:
            conn.execute(
                """
                INSERT INTO image_jobs (
                    id, job_type, status, algorithm, input_path,
                    output_path, result_json, error_message, created_at, updated_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, ?, ?, NULL)
                """,
                (job_id, job_type, "queued", algorithm, input_path, now, now),
            )
            conn.commit()


def update_job_state(
    job_id: str,
    *,
    status: str,
    output_path: str | None = None,
    result_json: dict[str, Any] | None = None,
    error_message: str | None = None,
    finished: bool = False,
) -> None:
    updated_at = utc_now_iso()
    finished_at = updated_at if finished else None
    with DB_LOCK:
        with closing(get_connection()) as conn:
            conn.execute(
                """
                UPDATE image_jobs
                SET status = ?,
                    output_path = COALESCE(?, output_path),
                    result_json = COALESCE(?, result_json),
                    error_message = ?,
                    updated_at = ?,
                    finished_at = COALESCE(?, finished_at)
                WHERE id = ?
                """,
                (
                    status,
                    output_path,
                    json.dumps(result_json, ensure_ascii=True) if result_json is not None else None,
                    error_message,
                    updated_at,
                    finished_at,
                    job_id,
                ),
            )
            conn.commit()


def fetch_job_row(job_id: str) -> sqlite3.Row | None:
    with DB_LOCK:
        with closing(get_connection()) as conn:
            return conn.execute("SELECT * FROM image_jobs WHERE id = ?", (job_id,)).fetchone()


def fetch_history_rows(limit: int, offset: int) -> list[sqlite3.Row]:
    with DB_LOCK:
        with closing(get_connection()) as conn:
            return conn.execute(
                """
                SELECT * FROM image_jobs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()


def parse_options(raw_options: str | None) -> dict[str, Any]:
    if not raw_options:
        return {}

    try:
        parsed = json.loads(raw_options)
    except json.JSONDecodeError as err:
        raise HTTPException(status_code=400, detail="options must be valid JSON") from err

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="options must decode to a JSON object")
    return parsed


def parse_bool_flag(raw_value: str | None, default: bool = False) -> bool:
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_algorithm(algorithm: str | None) -> str:
    value = (algorithm or DEFAULT_ALGORITHM).strip().lower()
    return value or DEFAULT_ALGORITHM


def validate_upload(upload: UploadFile, contents: bytes) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    content_type = (upload.content_type or "").lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Only PNG and JPG images are supported")
    if content_type and content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported image content type")
    if not contents:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="Uploaded image exceeds the 8 MB limit")
    return suffix


def read_and_store_upload(upload: UploadFile) -> str:
    contents = upload.file.read()
    suffix = validate_upload(upload, contents)

    try:
        with Image.open(BytesIO(contents)) as img:
            img.verify()
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="Uploaded file is not a valid image") from err

    relative_path = Path("uploads") / f"{uuid4().hex}{suffix}"
    target = STORAGE_DIR / relative_path
    target.write_bytes(contents)
    return relative_path.as_posix()


def asset_url(relative_path: str | None) -> str | None:
    if not relative_path:
        return None
    return f"/image/assets/{relative_path}"


def asset_path_from_url(url: str) -> str:
    prefix = "/image/assets/"
    if not url.startswith(prefix):
        raise HTTPException(status_code=400, detail="input_url must start with /image/assets/")
    return url.removeprefix(prefix)


def average_rgb(image: Image.Image) -> tuple[int, int, int]:
    rgb_image = image.convert("RGB")
    pixels = list(rgb_image.getdata())
    total = len(pixels) or 1
    red = sum(pixel[0] for pixel in pixels) // total
    green = sum(pixel[1] for pixel in pixels) // total
    blue = sum(pixel[2] for pixel in pixels) // total
    return red, green, blue


def build_analysis_summary(width: int, height: int, brightness: float) -> str:
    orientation = "landscape" if width >= height else "portrait"
    tone = "bright" if brightness >= 135 else "balanced" if brightness >= 90 else "dark"
    return (
        f"Detected a {orientation} image at {width}x{height} pixels with a {tone} global exposure profile. "
        "This placeholder analysis is structured so a real computer-vision model can replace it later."
    )


def analyze(image_path: str, options: dict[str, Any], algorithm: str) -> dict[str, Any]:
    absolute_path = STORAGE_DIR / image_path
    with Image.open(absolute_path) as img:
        rgb_image = img.convert("RGB")
        red, green, blue = average_rgb(rgb_image)
        grayscale = ImageOps.grayscale(rgb_image)
        histogram = grayscale.histogram()
        total_pixels = max(sum(histogram), 1)
        brightness = sum(index * count for index, count in enumerate(histogram)) / total_pixels
        contrast = max(histogram) / total_pixels
        width, height = rgb_image.size
        aspect_ratio = round(width / height, 4) if height else 0.0
        dominant_channel = max(
            (("red", red), ("green", green), ("blue", blue)),
            key=lambda item: item[1],
        )[0]

    summary = build_analysis_summary(width, height, brightness)
    labels = [
        "chart-like composition" if aspect_ratio >= 1.2 else "document-like framing",
        "high-luminance regions present" if brightness >= 130 else "mid-to-low luminance profile",
        f"dominant {dominant_channel} channel",
    ]
    if algorithm != DEFAULT_ALGORITHM:
        labels.append(f"processed via {algorithm}")
    if options:
        labels.append("custom options applied")

    return {
        "summary": summary,
        "labels": labels,
        "metrics": {
            "width": width,
            "height": height,
            "aspect_ratio": aspect_ratio,
            "average_rgb": {"r": red, "g": green, "b": blue},
            "brightness": round(brightness, 2),
            "contrast_score": round(contrast, 4),
        },
        "options_applied": options,
    }


def render(analysis: dict[str, Any], image_path: str, algorithm: str) -> str:
    source_path = STORAGE_DIR / image_path
    output_rel_path = Path("generated") / f"{uuid4().hex}.png"
    output_path = STORAGE_DIR / output_rel_path

    with Image.open(source_path) as original:
        base = original.convert("RGB")

    card_height = 170
    framed = ImageOps.expand(base, border=(0, card_height, 0, 0), fill=(5, 11, 20))
    overlay = Image.new("RGBA", framed.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rectangle((24, 20, framed.width - 24, 146), fill=(8, 17, 31, 220))
    draw.text((40, 34), "TradingAI Pro Image Analysis", fill=(226, 232, 240, 255))
    draw.text((40, 62), f"Algorithm: {algorithm}", fill=(125, 211, 252, 255))
    draw.text((40, 88), analysis["summary"][:110], fill=(203, 213, 225, 255))

    metrics = analysis.get("metrics", {})
    avg = metrics.get("average_rgb", {"r": 0, "g": 0, "b": 0})
    color_bar_start = framed.width - 250
    draw.rectangle((color_bar_start, 40, color_bar_start + 54, 94), fill=(avg["r"], 32, 32, 255))
    draw.rectangle((color_bar_start + 62, 40, color_bar_start + 116, 94), fill=(32, avg["g"], 32, 255))
    draw.rectangle((color_bar_start + 124, 40, color_bar_start + 178, 94), fill=(32, 32, avg["b"], 255))
    draw.text((color_bar_start, 104), "R / G / B", fill=(148, 163, 184, 255))

    output = Image.alpha_composite(framed.convert("RGBA"), overlay).convert("RGB")
    output.save(output_path, format="PNG")
    return output_rel_path.as_posix()


def serialize_job(row: sqlite3.Row) -> dict[str, Any]:
    result_json = json.loads(row["result_json"]) if row["result_json"] else None
    summary = result_json.get("summary") if isinstance(result_json, dict) else None
    return {
        "id": row["id"],
        "job_type": row["job_type"],
        "status": row["status"],
        "algorithm": row["algorithm"],
        "input_path": row["input_path"],
        "input_url": asset_url(row["input_path"]),
        "output_path": row["output_path"],
        "output_url": asset_url(row["output_path"]),
        "result": result_json,
        "summary": summary,
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "finished_at": row["finished_at"],
    }


def build_response(row: sqlite3.Row) -> dict[str, Any]:
    payload = serialize_job(row)
    payload["job_id"] = payload["id"]
    return payload


def process_job(job_id: str, image_path: str, algorithm: str, options: dict[str, Any], generate_image: bool) -> None:
    try:
        update_job_state(job_id, status="running", error_message=None)
        analysis = analyze(image_path, options, algorithm)
        output_path = render(analysis, image_path, algorithm) if generate_image else None
        result = {
            "analysis": analysis,
            "input_url": asset_url(image_path),
            "output_url": asset_url(output_path),
        }
        update_job_state(
            job_id,
            status="succeeded",
            output_path=output_path,
            result_json=result,
            error_message=None,
            finished=True,
        )
    except HTTPException as err:
        update_job_state(job_id, status="failed", error_message=err.detail, finished=True)
    except Exception as err:  # noqa: BLE001
        update_job_state(job_id, status="failed", error_message=str(err), finished=True)


def resolve_render_input(payload: RenderRequest) -> tuple[dict[str, Any], str, str, sqlite3.Row | None]:
    if payload.job_id:
        row = fetch_job_row(payload.job_id)
        if row is None:
            raise HTTPException(status_code=404, detail="job not found")
        serialized = serialize_job(row)
        result = serialized.get("result") or {}
        analysis = result.get("analysis")
        if not isinstance(analysis, dict):
            raise HTTPException(status_code=400, detail="job does not contain analysis data")
        return analysis, row["input_path"], row["algorithm"], row

    if not isinstance(payload.analysis, dict):
        raise HTTPException(status_code=400, detail="analysis is required when job_id is omitted")

    image_path = payload.input_path or (asset_path_from_url(payload.input_url) if payload.input_url else None)
    if not image_path:
        raise HTTPException(status_code=400, detail="input_path or input_url is required when job_id is omitted")
    return payload.analysis, image_path, normalize_algorithm(payload.algorithm), None


@app.get("/health")
def health() -> dict[str, Any]:
    ensure_storage()
    return {"ok": True}


@app.post("/image/analyze")
def analyze_image(
    file: UploadFile = File(...),
    algorithm: str = Form(DEFAULT_ALGORITHM),
    options: str | None = Form(None),
    generate_image: str | None = Form(None),
) -> dict[str, Any]:
    ensure_storage()
    normalized_algorithm = normalize_algorithm(algorithm)
    parsed_options = parse_options(options)
    should_render = parse_bool_flag(generate_image, default=True)
    image_path = read_and_store_upload(file)
    job_id = uuid4().hex
    insert_job(job_id, "sync", normalized_algorithm, image_path)
    process_job(job_id, image_path, normalized_algorithm, parsed_options, should_render)
    row = fetch_job_row(job_id)
    if row is None:
        raise HTTPException(status_code=500, detail="failed to persist sync job")
    payload = build_response(row)
    if payload["status"] == "failed":
        raise HTTPException(status_code=500, detail=payload["error_message"] or "analysis failed")
    return payload


@app.post("/image/jobs")
def create_job(
    file: UploadFile = File(...),
    algorithm: str = Form(DEFAULT_ALGORITHM),
    options: str | None = Form(None),
    generate_image: str | None = Form(None),
) -> dict[str, Any]:
    ensure_storage()
    normalized_algorithm = normalize_algorithm(algorithm)
    parsed_options = parse_options(options)
    should_render = parse_bool_flag(generate_image, default=True)
    image_path = read_and_store_upload(file)
    job_id = uuid4().hex
    insert_job(job_id, "async", normalized_algorithm, image_path)
    EXECUTOR.submit(process_job, job_id, image_path, normalized_algorithm, parsed_options, should_render)
    row = fetch_job_row(job_id)
    if row is None:
        raise HTTPException(status_code=500, detail="failed to create async job")
    return build_response(row)


@app.get("/image/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    row = fetch_job_row(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="job not found")
    return build_response(row)


@app.get("/image/history")
def get_history(page: int = 1, page_size: int = DEFAULT_HISTORY_LIMIT) -> dict[str, Any]:
    normalized_page = max(page, 1)
    normalized_size = min(max(page_size, 1), MAX_HISTORY_LIMIT)
    rows = fetch_history_rows(normalized_size, (normalized_page - 1) * normalized_size)
    items = [serialize_job(row) for row in rows]
    return {
        "items": items,
        "page": normalized_page,
        "page_size": normalized_size,
    }


@app.post("/image/render")
def render_image(payload: RenderRequest) -> dict[str, Any]:
    ensure_storage()
    analysis, image_path, algorithm, row = resolve_render_input(payload)
    output_path = render(analysis, image_path, algorithm)
    if row is not None:
        serialized = serialize_job(row)
        result = serialized.get("result") or {}
        result["analysis"] = analysis
        result["input_url"] = asset_url(image_path)
        result["output_url"] = asset_url(output_path)
        update_job_state(
            row["id"],
            status=row["status"],
            output_path=output_path,
            result_json=result,
            error_message=row["error_message"],
            finished=False,
        )
    return {
        "output_path": output_path,
        "output_url": asset_url(output_path),
        "input_url": asset_url(image_path),
    }
