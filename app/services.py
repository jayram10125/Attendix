import base64
import json
import math
from datetime import datetime, timedelta
from io import BytesIO
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from flask import current_app


def local_now():
    return datetime.now(ZoneInfo(current_app.config.get("APP_TIMEZONE", "Asia/Kolkata")))


def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000
    a = math.sin(math.radians(lat2-lat1)/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(math.radians(lon2-lon1)/2)**2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))


def validate_coordinates(lat, lon):
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        raise ValueError("Allow location access and try again.")
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Invalid coordinates.")
    return lat, lon


def schedule_status(schedule, moment):
    if str(moment.weekday()) not in schedule.working_days.split(","):
        raise ValueError("Today is not a scheduled work day.")
    start = datetime.combine(moment.date(), schedule.start_time, moment.tzinfo)
    end = datetime.combine(moment.date(), schedule.end_time, moment.tzinfo)
    if end <= start:
        raise ValueError("Schedule must end after it starts.")
    if moment < start or moment > end:
        raise ValueError("Attendance is allowed only during scheduled hours.")
    return "late" if moment > start + timedelta(minutes=schedule.grace_minutes) else "present"


_detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def extract_face(data_url):
    if not data_url or not data_url.startswith("data:image/jpeg;base64,"):
        raise ValueError("Capture a camera photo first.")
    try:
        raw = base64.b64decode(data_url.split(",", 1)[1], validate=True)
        if len(raw) > 2_000_000:
            raise ValueError("Photo is too large.")
        image = Image.open(BytesIO(raw))
        image.verify()
        image = Image.open(BytesIO(raw)).convert("L")
        if image.width < 160 or image.height < 160 or image.width > 2000 or image.height > 2000:
            raise ValueError("Photo resolution is unsupported.")
        gray = np.array(image)
    except (ValueError, UnidentifiedImageError, OSError, base64.binascii.Error):
        raise ValueError("Use a valid camera photo.")
    faces = _detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(70, 70))
    if len(faces) != 1:
        raise ValueError("Show exactly one clear, front-facing face.")
    x, y, w, h = faces[0]
    face = cv2.resize(gray[y:y+h, x:x+w], (160, 160))
    return cv2.equalizeHist(face)


def serialize_face(face):
    return cv2.imencode(".png", face)[1].tobytes()


def serialize_faces(faces):
    if len(faces) != 3:
        raise ValueError("Capture three face photos for registration.")
    return b"ATTENDIX_FACES_V1\n" + json.dumps([base64.b64encode(serialize_face(face)).decode("ascii") for face in faces]).encode("ascii")


def reference_faces(reference_bytes):
    if reference_bytes.startswith(b"ATTENDIX_FACES_V1\n"):
        try:
            encoded = json.loads(reference_bytes.split(b"\n", 1)[1])
            references = [cv2.imdecode(np.frombuffer(base64.b64decode(item, validate=True), dtype=np.uint8), cv2.IMREAD_GRAYSCALE) for item in encoded]
        except (ValueError, TypeError, json.JSONDecodeError, base64.binascii.Error):
            return []
    else:
        references = [cv2.imdecode(np.frombuffer(reference_bytes, dtype=np.uint8), cv2.IMREAD_GRAYSCALE)]
    references = [face for face in references if face is not None and face.shape == (160, 160)]
    return references


def face_confidence(reference_bytes, submitted):
    references = reference_faces(reference_bytes)
    if not references:
        return float("inf")
    recognizer = cv2.face.LBPHFaceRecognizer_create(radius=1, neighbors=8, grid_x=8, grid_y=8)
    recognizer.train(references, np.array([1] * len(references), dtype=np.int32))
    _, confidence = recognizer.predict(submitted)
    return confidence


def verify_face(reference_bytes, submitted):
    return face_confidence(reference_bytes, submitted) <= 45


def match_registered_face(identities, submitted):
    scores = sorted((face_confidence(identity.face_data, submitted), identity.user_id) for identity in identities)
    if not scores or scores[0][0] > 45:
        return None
    if len(scores) > 1 and scores[1][0] - scores[0][0] < 5:
        return None
    return scores[0][1]
