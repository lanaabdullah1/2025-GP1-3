import cv2
import time
import os
import threading

import queue

import mediapipe as mp
import numpy as np

from ultralytics import YOLO


import torch
import torch.nn.functional as F

from pi_torchreid.utils import FeatureExtractor

import json


from model.query import (
    create_alert,
    get_security_fields,
    log_sms,
    send_sms_gateway
)

camera_states = {}
camera_states_lock = threading.Lock()


def get_camera_state(camera_id):
    with camera_states_lock:

        if camera_id not in camera_states:

            camera_states[camera_id] = {
                "roi": None,
                "roi_version": 0,
                "stream_id": 0
            }

        return camera_states[camera_id]

def stop_camera_stream(camera_id):

    state = get_camera_state(camera_id)

    with camera_states_lock:
        state["stream_id"] += 1


camera_source = None

last_alert_time = {}

camera_last_frame_time = {}


ALERT_COOLDOWN = 15

# =========================
# Hand
# =========================
HAND_MEDIUM_TIME_LIMIT = 3
HAND_HIGH_TIME_LIMIT = 5
HAND_LOST_GRACE = 3.0

# =========================
# Head 
# =========================
HEAD_MEDIUM_TIME_LIMIT = 5
HEAD_HIGH_TIME_LIMIT = 10

FACE_POSE_POINTS = {
    1: (0.0, 0.0, 0.0),
    152: (0.0, -63.6, -12.5),
    33: (-43.3, 32.7, -26.0),
    263: (43.3, 32.7, -26.0),
    61: (-28.9, -28.9, -24.1),
    291: (28.9, -28.9, -24.1),
    199: (0.0, -41.2, -7.1)
}


# for to turn off alerts for now
ENABLE_HAND_ALERTS = False

#old ver
#mp_hands = mp.solutions.hands

#new ver
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
PoseLandmarker = mp.tasks.vision.PoseLandmarker
VisionRunningMode = mp.tasks.vision.RunningMode

# =========================
# Head 
# =========================
FaceLandmarker = mp.tasks.vision.FaceLandmarker
FaceLandmarkerOptions = mp.tasks.vision.FaceLandmarkerOptions


# =========================
# YOLO + PER-CAMERA TRACKING
# =========================

camera_yolo_models = {}
camera_yolo_models_lock = threading.Lock()




def get_camera_yolo_model(camera_id):

    with camera_yolo_models_lock:

        if camera_id not in camera_yolo_models:

            camera_yolo_models[camera_id] = YOLO(
                "yolov8n_openvino_model/"
            )

        return camera_yolo_models[camera_id]

# =========================
# PERSON RE-ID
# =========================
''' OLD CODE 
reid_extractor = FeatureExtractor(
    model_name="osnet_x1_0",
    device="cpu"
)
'''

reid_model_path = os.path.join(
    os.path.dirname(__file__),
    "osnet_x1_0_msmt17_combineall_256x128_amsgrad_ep150_stp60_lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth"
)

reid_extractor = FeatureExtractor(
    model_name="osnet_x1_0",
    model_path=reid_model_path,
    device="cpu"
)

reid_lock = threading.Lock()

###so sends 1 sms only
sms_sent = False




def set_roi(x1, y1, x2, y2, camera_id=1):

    state = get_camera_state(camera_id)

    state["roi"] = (
        int(x1),
        int(y1),
        int(x2),
        int(y2)
    )

    state["roi_version"] += 1


def reset_roi(camera_id=1):

    state = get_camera_state(camera_id)

    state["roi"] = None
    state["roi_version"] += 1


def set_camera(src):
    global camera_source

    camera_source = src





def get_camera():
    return camera_source



def point_inside_roi(x, y, current_roi):
    if not current_roi:
        return False

    x1, y1, x2, y2 = current_roi

    return (
        x1 <= x <= x2 and
        y1 <= y <= y2
    )


def person_inside_roi(person, current_roi):

    if not current_roi:
        return False

    x1, y1, x2, y2, conf = person
    rx1, ry1, rx2, ry2 = current_roi

    intersection_x1 = max(x1, rx1)
    intersection_y1 = max(y1, ry1)
    intersection_x2 = min(x2, rx2)
    intersection_y2 = min(y2, ry2)

    if (
        intersection_x2 <= intersection_x1
        or intersection_y2 <= intersection_y1
    ):
        return False

    intersection_area = (
        (intersection_x2 - intersection_x1) *
        (intersection_y2 - intersection_y1)
    )

    person_area = (
        (x2 - x1) *
        (y2 - y1)
    )

    if person_area <= 0:
        return False

    overlap_ratio = (
        intersection_area / person_area
    )

    return overlap_ratio >= 0.20

def face_inside_roi(face_landmarks, frame, current_roi):
    if not current_roi:
        return False

    h, w = frame.shape[:2]
    nose = face_landmarks[1]
    x = int(nose.x * w)
    y = int(nose.y * h)

    return point_inside_roi(x, y, current_roi)


def head_looks_toward_roi(head_pose, face_landmarks, frame, current_roi):

    if head_pose is None or face_landmarks is None or current_roi is None:
        return False

    h, w = frame.shape[:2]

    # Nose position
    nose = face_landmarks[1]
    nose_x = nose.x * w
    nose_y = nose.y * h

    # Center of the selected ROI
    x1, y1, x2, y2 = current_roi
    roi_x = (x1 + x2) / 2
    roi_y = (y1 + y2) / 2

    # ROI position relative to the nose
    dx = roi_x - nose_x
    dy = roi_y - nose_y

    horizontal_tolerance = w * 0.32
    vertical_tolerance = h * 0.32

    direction = head_pose["direction"]

    if direction == "Looking Left":
        return (
            dx > 0
            and abs(dx) >= 15
            and abs(dx) >= abs(dy) * 0.35
        )

    elif direction == "Looking Right":
        return (
            dx < 0
            and abs(dx) >= 15
            and abs(dx) >= abs(dy) * 0.35
        )

    elif direction == "Looking Up":
        return (
            dy < 0
            and abs(dy) >= 10
            and abs(dy) >= abs(dx) * 0.35
        )

    elif direction == "Looking Down":
        return (
            dy > 0
            and abs(dy) >= 10
            and abs(dy) >= abs(dx) * 0.35
        )

    elif direction == "Looking Forward":
        return (
            abs(dx) <= horizontal_tolerance
            and abs(dy) <= vertical_tolerance
        )

    return False

def calculate_head_pose(face_landmarks, frame):

    h, w = frame.shape[:2]

    image_points = []
    model_points = []

    for landmark_id, model_point in FACE_POSE_POINTS.items():

        landmark = face_landmarks[landmark_id]

        image_points.append(
            (
                landmark.x * w,
                landmark.y * h
            )
        )

        model_points.append(model_point)

    image_points = np.array(
        image_points,
        dtype=np.float64
    )

    model_points = np.array(
        model_points,
        dtype=np.float64
    )

    focal_length = w

    center = (
        w / 2,
        h / 2
    )

    camera_matrix = np.array(
        [
            [focal_length, 0, center[0]],
            [0, focal_length, center[1]],
            [0, 0, 1]
        ],
        dtype=np.float64
    )

    distortion = np.zeros(
        (4, 1),
        dtype=np.float64
    )

    success, rotation_vector, translation_vector = cv2.solvePnP(
        model_points,
        image_points,
        camera_matrix,
        distortion,
        flags=cv2.SOLVEPNP_ITERATIVE
    )

    if not success:
        return None

    rotation_matrix, _ = cv2.Rodrigues(
        rotation_vector
    )

    angles, _, _, _, _, _ = cv2.RQDecomp3x3(
        rotation_matrix
    )

    
    # Raw angles from OpenCV
    raw_pitch = float(angles[0])
    yaw = float(angles[1])
    roll = float(angles[2])

    # Normalize pitch around zero instead of +/-180
    pitch = ((raw_pitch + 90) % 180) - 90

    return {
        "pitch": pitch,
        "yaw": yaw,
        "roll": roll,
        "raw_pitch": raw_pitch,
        "direction": "Calibrating..."
    }



    


def hand_inside_roi(hand_landmarks, frame, current_roi):
    if not current_roi:
        return False

    h, w = frame.shape[:2]

    for landmark in hand_landmarks:
        x = int(landmark.x * w)
        y = int(landmark.y * h)

        if point_inside_roi(x, y, current_roi):
            return True

    return False


def draw_hand_landmarks(frame, hand_landmarks):

    h, w = frame.shape[:2]

    points = []

    for landmark in hand_landmarks:

        x = int(landmark.x * w)
        y = int(landmark.y * h)

        points.append((x, y))

        cv2.circle(
            frame,
            (x, y),
            3,
            (0, 255, 0),
            -1
        )

    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17)
    ]

    for start, end in connections:

        cv2.line(
            frame,
            points[start],
            points[end],
            (0, 255, 0),
            2
        )
    


def record_clip(source, clip_filename):

    cap = cv2.VideoCapture(source)

    fourcc = cv2.VideoWriter_fourcc(*'mp4v')

    video_writer = cv2.VideoWriter(
        clip_filename,
        fourcc,
        20.0,
        (480, 270)
    )

    start = time.time()

    while time.time() - start < 10:

        ret, frame = cap.read()

        if not ret:
            break

        frame = cv2.resize(
            frame,
            (480, 270)
        )

        video_writer.write(frame)

    video_writer.release()

    cap.release()


# =========================
# SIMPLE GLOBAL PERSON IDs
# =========================

person_gallery = {}
next_person_id = 1

gallery_lock = threading.Lock()

REID_THRESHOLD = 0.65
MAX_EMBEDDINGS_PER_PERSON = 20

# Gallery admission rules.
# Matching can succeed at REID_THRESHOLD,
# but learning a new gallery embedding requires stronger evidence.
GALLERY_UPDATE_MIN_SIMILARITY = 0.80
GALLERY_UPDATE_MIN_MARGIN = 0.10
GALLERY_DUPLICATE_SIMILARITY = 0.95

#REID_DEBUG = True
REID_DEBUG = False

REID_DEBUG_DIR = "debug_reid"


# ============================================================
# TEMPORARY IDENTITY DIAGNOSTICS
# Background writer so camera processing never waits for disk
# ============================================================

IDENTITY_DIAGNOSTICS = True

IDENTITY_DIAG_DIR = os.path.join(
    os.path.dirname(__file__),
    "debug_identity"
)

IDENTITY_DIAG_FILE = os.path.join(
    IDENTITY_DIAG_DIR,
    "identity_debug.jsonl"
)

# Camera threads only place events here.
# Disk writing happens in a separate daemon thread.
IDENTITY_DIAG_QUEUE = queue.Queue(maxsize=1000)

identity_diag_dropped = 0


def identity_diag_writer():

    os.makedirs(
        IDENTITY_DIAG_DIR,
        exist_ok=True
    )

    with open(
        IDENTITY_DIAG_FILE,
        "a",
        encoding="utf-8"
    ) as f:

        pending_writes = 0
        last_flush = time.monotonic()

        while True:

            try:
                line = IDENTITY_DIAG_QUEUE.get(
                    timeout=0.5
                )

            except queue.Empty:

                if pending_writes > 0:
                    f.flush()
                    pending_writes = 0
                    last_flush = time.monotonic()

                continue

            f.write(line + "\n")

            pending_writes += 1

            if (
                pending_writes >= 20
                or time.monotonic() - last_flush >= 1.0
            ):

                f.flush()

                pending_writes = 0
                last_flush = time.monotonic()

            IDENTITY_DIAG_QUEUE.task_done()


def identity_diag(event, **data):

    global identity_diag_dropped

    if not IDENTITY_DIAGNOSTICS:
        return

    record = {
        "time": time.time(),
        "event": event,
        **data
    }

    line = json.dumps(
        record,
        ensure_ascii=False
    )

    try:

        IDENTITY_DIAG_QUEUE.put_nowait(
            line
        )

    except queue.Full:

        # Debugging must NEVER slow or block the camera.
        # If the logger cannot keep up, drop the debug event.
        identity_diag_dropped += 1


if IDENTITY_DIAGNOSTICS:

    threading.Thread(
        target=identity_diag_writer,
        daemon=True,
        name="identity-diagnostic-writer"
    ).start()




def get_person_embedding(
    person_crop,
    camera_id=None,
    track_id=None
):

    if (
        person_crop is None
        or person_crop.size == 0
    ):
        return None

    try:

        crop_rgb = cv2.cvtColor(
            person_crop,
            cv2.COLOR_BGR2RGB
        )

        lock_wait_start = time.perf_counter()

        with reid_lock:

            lock_wait_ms = (
                time.perf_counter()
                - lock_wait_start
            ) * 1000

            inference_start = time.perf_counter()

            features = reid_extractor(
                [crop_rgb]
            )

            inference_ms = (
                time.perf_counter()
                - inference_start
            ) * 1000

        embedding = features[0]

        embedding = F.normalize(
            embedding,
            p=2,
            dim=0
        )

        if REID_DEBUG:

            print(
                f"[REID TIMING] "
                f"Camera {camera_id} | "
                f"Track {track_id} | "
                f"Lock wait: {lock_wait_ms:.1f} ms | "
                f"OSNet: {inference_ms:.1f} ms"
            )

        return embedding.cpu()

    except Exception as e:

        print(
            "[REID] Embedding error:",
            e
        )

        return None


def get_aggregated_person_embedding(
    person_crops,
    camera_id=None,
    track_id=None
):

    if not person_crops:
        return None

    try:

        crops_rgb = [
            cv2.cvtColor(
                crop,
                cv2.COLOR_BGR2RGB
            )
            for crop in person_crops
            if crop is not None and crop.size > 0
        ]

        if not crops_rgb:
            return None

        lock_wait_start = time.perf_counter()

        with reid_lock:

            lock_wait_ms = (
                time.perf_counter()
                - lock_wait_start
            ) * 1000

            inference_start = time.perf_counter()

            features = reid_extractor(
                crops_rgb
            )

            inference_ms = (
                time.perf_counter()
                - inference_start
            ) * 1000

        # Normalize each crop's embedding
        features = F.normalize(
            features,
            p=2,
            dim=1
        )

        # Average the 3 embeddings
        aggregated_embedding = features.mean(
            dim=0
        )

        # Normalize the final combined embedding
        aggregated_embedding = F.normalize(
            aggregated_embedding,
            p=2,
            dim=0
        )

        if REID_DEBUG:

            print(
                f"[REID BATCH TIMING] "
                f"Camera {camera_id} | "
                f"Track {track_id} | "
                f"Crops: {len(crops_rgb)} | "
                f"Lock wait: {lock_wait_ms:.1f} ms | "
                f"OSNet batch: {inference_ms:.1f} ms"
            )

        return aggregated_embedding.cpu()

    except Exception as e:

        print(
            "[REID] Batch embedding error:",
            e
        )

        return None


def find_best_gallery_match(
    embedding
):

    if embedding is None:
        return None, -1.0

    best_person_id = None
    best_similarity = -1.0

    with gallery_lock:

        for person_id, saved_embeddings in person_gallery.items():

            similarities = []

            for saved_embedding in saved_embeddings:

                similarity = F.cosine_similarity(
                    embedding.unsqueeze(0),
                    saved_embedding.unsqueeze(0)
                ).item()

                similarities.append(similarity)

            if not similarities:
                continue

            person_similarity = max(
                similarities
            )

            if person_similarity > best_similarity:

                best_similarity = person_similarity
                best_person_id = person_id

    return (
        best_person_id,
        best_similarity
    )


def get_global_person_id(
    embedding,
    camera_id=None,
    track_id=None
):

    global next_person_id

    if embedding is None:
        return None

    best_person_id = None
    best_similarity = -1.0

    person_scores = {}

    gallery_wait_start = time.perf_counter()

    with gallery_lock:

        gallery_wait_ms = (
            time.perf_counter()
            - gallery_wait_start
        ) * 1000

        compare_start = time.perf_counter()

        # Compare against every known person
        for person_id, saved_embeddings in person_gallery.items():

            similarities = []

            for saved_embedding in saved_embeddings:

                similarity = F.cosine_similarity(
                    embedding.unsqueeze(0),
                    saved_embedding.unsqueeze(0)
                ).item()

                similarities.append(similarity)

            if not similarities:
                continue

            # Best previous view for this person
            person_similarity = max(
                similarities
            )

            person_scores[
                person_id
            ] = person_similarity

            if person_similarity > best_similarity:

                best_similarity = person_similarity
                best_person_id = person_id

        compare_ms = (
            time.perf_counter()
            - compare_start
        ) * 1000




        if REID_DEBUG:

            if person_scores:

                score_text = " | ".join(
                    f"Person {person_id}: "
                    f"{score:.3f}"
                    for person_id, score
                    in sorted(person_scores.items())
                )

            else:

                score_text = "Gallery empty"

            print(
                f"[REID DETAILS] "
                f"Camera {camera_id} | "
                f"Track {track_id} | "
                f"{score_text}"
            )

            print(
                f"[REID GALLERY TIMING] "
                f"Camera {camera_id} | "
                f"Track {track_id} | "
                f"Lock wait: {gallery_wait_ms:.1f} ms | "
                f"Compare: {compare_ms:.1f} ms"
            )


        sorted_scores = sorted(
            person_scores.items(),
            key=lambda item: item[1],
            reverse=True
        )

        second_best_person_id = None
        second_best_similarity = -1.0

        if len(sorted_scores) >= 2:

            second_best_person_id = sorted_scores[1][0]
            second_best_similarity = sorted_scores[1][1]

        margin = (
            best_similarity - second_best_similarity
            if second_best_similarity >= 0
            else None
        )

        identity_diag(
            "REID_DECISION_DATA",
            camera_id=camera_id,
            track_id=track_id,

            all_scores={
                str(person_id): score
                for person_id, score
                in person_scores.items()
            },

            best_person_id=best_person_id,
            best_similarity=best_similarity,

            second_best_person_id=second_best_person_id,
            second_best_similarity=second_best_similarity,

            margin=margin,

            threshold=REID_THRESHOLD,

            current_code_decision=(
                "MATCH"
                if (
                    best_person_id is not None
                    and best_similarity >= REID_THRESHOLD
                )
                else "NEW"
            ),

            gallery_sizes={
                str(person_id): len(embeddings)
                for person_id, embeddings
                in person_gallery.items()
            }
        )
    


    # Existing person
    if (
        best_person_id is not None
        and best_similarity >= REID_THRESHOLD
    ):
        
        # ---------------------------------------------------------
        # SAFE + DIVERSE GALLERY UPDATE
        # Matching a person does NOT automatically mean
        # this embedding is trustworthy enough to learn from.
        # ---------------------------------------------------------

        strong_enough = (
            best_similarity >= GALLERY_UPDATE_MIN_SIMILARITY
        )

        margin_good = (
            margin is None
            or margin >= GALLERY_UPDATE_MIN_MARGIN
        )

        not_duplicate = (
            best_similarity < GALLERY_DUPLICATE_SIMILARITY
        )

        if (
            strong_enough
            and margin_good
            and not_duplicate
        ):

            identity_diag(
                "GALLERY_ADD_MATCH",
                camera_id=camera_id,
                track_id=track_id,
                person_id=best_person_id,
                similarity=best_similarity,
                second_best_person_id=second_best_person_id,
                second_best_similarity=second_best_similarity,
                margin=margin,
                gallery_size_before=len(
                    person_gallery[best_person_id]
                )
            )

            person_gallery[
                best_person_id
            ].append(embedding)

            person_gallery[
                best_person_id
            ] = person_gallery[
                best_person_id
            ][-MAX_EMBEDDINGS_PER_PERSON:]

        else:

            skip_reasons = []

            if not strong_enough:
                skip_reasons.append("similarity_not_strong_enough")

            if not margin_good:
                skip_reasons.append("best_vs_second_best_too_close")

            if not not_duplicate:
                skip_reasons.append("near_duplicate")

            identity_diag(
                "GALLERY_SKIP_UPDATE",
                camera_id=camera_id,
                track_id=track_id,
                person_id=best_person_id,
                similarity=best_similarity,
                second_best_person_id=second_best_person_id,
                second_best_similarity=second_best_similarity,
                margin=margin,
                reasons=skip_reasons,
                gallery_size=len(
                    person_gallery[best_person_id]
                )
            )

        if REID_DEBUG:

            print(
                f"[REID DECISION] "
                f"Camera {camera_id} | "
                f"Track {track_id} | "
                f"MATCH Person {best_person_id} | "
                f"Score {best_similarity:.3f} | "
                f"Threshold {REID_THRESHOLD:.3f}"
            )

        return (
            best_person_id,
            best_similarity
        )



    #New person
    person_id = next_person_id
    next_person_id += 1


    identity_diag(
        "GALLERY_CREATE_PERSON",
        camera_id=camera_id,
        track_id=track_id,
        new_person_id=person_id
    )

    person_gallery[
        person_id
    ] = [embedding]

    if REID_DEBUG:

        print(
            f"[REID DECISION] "
            f"Camera {camera_id} | "
            f"Track {track_id} | "
            f"NEW Person {person_id} | "
            f"Best previous Person "
            f"{best_person_id} | "
            f"Best score {best_similarity:.3f} | "
            f"Threshold {REID_THRESHOLD:.3f}"
        )

    return (
        person_id,
        1.0
    )


def calculate_box_iou(box_a, box_b):

    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b

    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)

    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)

    intersection = iw * ih

    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)

    union = area_a + area_b - intersection

    if union <= 0:
        return 0.0

    return intersection / union



def classify_reid_crop_state(
    reid_crop_good,
    area_ratio,
    box_height,
    frame_h
):

    if not reid_crop_good:
        return "BAD"

    height_ratio = (
        box_height / frame_h
        if frame_h > 0
        else 0.0
    )

    # Only skip Pose when the crop is very obviously usable.
    # Smaller/farther crops are AMBIGUOUS, not automatically BAD.
    if (
        area_ratio >= 0.10
        and height_ratio >= 0.50
    ):
        return "CLEAR"

    return "AMBIGUOUS"


def pose_allows_reid_crop(
    worker_pose,
    person_crop
):

    if (
        worker_pose is None
        or person_crop is None
        or person_crop.size == 0
    ):
        return False, {}

    rgb = cv2.cvtColor(
        person_crop,
        cv2.COLOR_BGR2RGB
    )

    mp_image = mp.Image(
        image_format=mp.ImageFormat.SRGB,
        data=rgb
    )

    result = worker_pose.detect(
        mp_image
    )

    if not result.pose_landmarks:
        return False, {
            "pose_found": False
        }

    landmarks = result.pose_landmarks[0]

    VISIBILITY_THRESHOLD = 0.55
    PRESENCE_THRESHOLD = 0.50

    def visible(index):

        landmark = landmarks[index]

        visibility = (
            landmark.visibility
            if landmark.visibility is not None
            else 1.0
        )

        presence = (
            landmark.presence
            if landmark.presence is not None
            else 1.0
        )

        return (
            visibility >= VISIBILITY_THRESHOLD
            and presence >= PRESENCE_THRESHOLD
        )

    nose = visible(0)

    left_shoulder = visible(11)
    right_shoulder = visible(12)

    left_hip = visible(23)
    right_hip = visible(24)

    left_knee = visible(25)
    right_knee = visible(26)

    shoulder_visible = (
        left_shoulder
        or right_shoulder
    )

    hip_visible = (
        left_hip
        or right_hip
    )

    extra_visible = (
        nose
        or (
            left_shoulder
            and right_shoulder
        )
        or left_knee
        or right_knee
    )

    allowed = (
        shoulder_visible
        and hip_visible
        and extra_visible
    )

    details = {
        "pose_found": True,
        "nose": bool(nose),
        "left_shoulder": bool(left_shoulder),
        "right_shoulder": bool(right_shoulder),
        "left_hip": bool(left_hip),
        "right_hip": bool(right_hip),
        "left_knee": bool(left_knee),
        "right_knee": bool(right_knee),
        "allowed": bool(allowed)
    }

    return allowed, details




def generate_frames(source, camera_id=1):

   
    global camera_last_frame_time
    global sms_sent

    state = get_camera_state(camera_id)

    # =========================
    # YOLO + BYTETRACK MODEL
    # =========================

    camera_yolo_model = get_camera_yolo_model(
        camera_id
    )

    # Maps ByteTrack local ID -> Eyecept ReID person ID
    track_identity_map = {}

    # ============================================================
    # MULTI-FRAME REID
    # ============================================================

    REID_SAMPLES_NEEDED = 3
    REID_SAMPLE_GAP = 5
    REID_CONFIRMATIONS_NEEDED = 2


    # track_id -> list of good person crops waiting for one batched OSNet call
    track_reid_crops = {}

    # track_id -> frame number of most recent ReID sample
    track_reid_last_sample_frame = {}

    # track_id -> tentative existing-person match waiting for confirmation
    track_reid_pending = {}


    # Tracks waiting until enough of the body is visible for ReID
    track_reid_waiting_clear = set()

    # Pose is lazy-loaded.
    # If no ambiguous crop ever appears, Pose never loads or runs.
    worker_pose = None


    frame_counter = 0
    
    # ROI HEAD ATTENTION TEST
    head_roi_start = None
    head_roi_duration = 0.0
    roi_facing = False

    # =========================
    # HEAD POSE CALIBRATION
    # =========================

    head_calibration_samples = []

    neutral_pitch = None
    neutral_yaw = None

    HEAD_CALIBRATION_FRAMES = 30

    # Thresholds in degrees
    HEAD_YAW_THRESHOLD = 9


    HEAD_UP_THRESHOLD = 9
    HEAD_DOWN_THRESHOLD = 18

    track_first_seen = {}
    track_last_seen = {}

    previous_active_tracks = set()

    previous_person_conflicts = set()

   

    with camera_states_lock:
        state["stream_id"] += 1
        local_stream = state["stream_id"]

    ''' OLD CODE
    worker_hands = mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5
    )
    '''

    #=======================
    #NEW CODE FOR ABOVE 
    #=======================

    hand_model_path = os.path.join(
    os.path.dirname(__file__),
    "hand_landmarker.task"
    )

    pose_model_path = os.path.join(
    os.path.dirname(__file__),
    "pose_landmarker_lite.task"
)

    hand_options = HandLandmarkerOptions(
        base_options=BaseOptions(
            model_asset_path=hand_model_path
        ),
        running_mode=VisionRunningMode.VIDEO,
        num_hands=1,
        min_hand_detection_confidence=0.5,
        min_hand_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )

    worker_hands = HandLandmarker.create_from_options(
        hand_options
    )


    face_model_path = os.path.join(
    os.path.dirname(__file__),
    "face_landmarker.task"
    )

    face_options = FaceLandmarkerOptions(
        base_options=BaseOptions(
            model_asset_path=face_model_path
        ),
        running_mode=VisionRunningMode.VIDEO,
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5
    )

    worker_face_mesh = FaceLandmarker.create_from_options(
        face_options
    )
   

    hand_interaction_start = None
    hand_last_seen = None
    hand_lost_since = None
    hand_alerted_levels = set()


    # =========================
    # PERFORMANCE TEST
    # =========================

    perf_start_time = time.time()
    perf_frame_count = 0

    total_read_time = 0
    total_yolo_time = 0
    total_reid_time = 0
    total_hand_time = 0
    total_encode_time = 0

    current_fps = 0


    # =========================
    # =========================




    if isinstance(source, int):
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(source)

    if not os.path.exists("snapshots"):
        os.makedirs("snapshots")

    if not os.path.exists("clips"):
        os.makedirs("clips")

    local_version = state["roi_version"]

    

    while True:

        if local_stream != state["stream_id"]:
            break

        #success, frame = cap.read()

        # ============================================================
        # PERFORMANCE TEST - CAMERA READ TIME - DELETE LATER
        # ============================================================

        read_start = time.perf_counter()

        success, frame = cap.read()

        read_time = time.perf_counter() - read_start
        total_read_time += read_time

        # ============================================================
        # END PERFORMANCE TEST - CAMERA READ TIME - DELETE LATER
        # ============================================================

        

        if success:
            camera_last_frame_time[camera_id] = time.time()

            frame_counter += 1

        if not success:
            break

    

        

       

      

        frame = cv2.resize(
            frame,
            (480, 270)
        )




        if local_version != state["roi_version"]:

            hand_interaction_start = None
            hand_last_seen = None
            hand_lost_since = None
            hand_alerted_levels.clear()

            head_roi_start = None
            head_roi_duration = 0.0

            local_version = state["roi_version"]

        h, w = frame.shape[:2]

        head_pose = None
        face_landmarks = None

        current_roi = state["roi"] 

        if current_roi:

            x1, y1, x2, y2 = current_roi

            x1 = max(0, min(x1, w))
            x2 = max(0, min(x2, w))

            y1 = max(0, min(y1, h))
            y2 = max(0, min(y2, h))

            cv2.rectangle(
                frame,
                (x1, y1),
                (x2, y2),
                (0, 255, 0),
                2
            )



            current_roi = (
                x1,
                y1,
                x2,
                y2
            )

            # ============================================================
            # YOLO + BYTETRACK
            # ============================================================

            yolo_start = time.perf_counter()

           

            tracking_results = camera_yolo_model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                imgsz=320,
                classes=[0],
                conf=0.65,
                device="intel:gpu",
                verbose=False
            )

            yolo_time = time.perf_counter() - yolo_start
            total_yolo_time += yolo_time


            # ============================================================
            # PROCESS TRACKED PEOPLE
            # ============================================================

            result = tracking_results[0]

            if (
                result.boxes is not None
                and result.boxes.id is not None
            ):

                boxes = (
                    result.boxes.xyxy
                    .cpu()
                    .numpy()
                    .astype(int)
                )

                track_ids = (
                    result.boxes.id
                    .int()
                    .cpu()
                    .tolist()
                )

                confidences = (
                    result.boxes.conf
                    .cpu()
                    .tolist()
                )


                current_active_tracks = set(track_ids)

                if current_active_tracks != previous_active_tracks:

                    identity_diag(
                        "TRACK_SET_CHANGED",
                        camera_id=camera_id,
                        frame=frame_counter,
                        previous_tracks=sorted(previous_active_tracks),
                        current_tracks=sorted(current_active_tracks)
                    )

                previous_active_tracks = current_active_tracks.copy()


                for box, track_id, conf in zip(
                    boxes,
                    track_ids,
                    confidences
                ):

                    px1, py1, px2, py2 = box

                    # Keep coordinates inside frame
                    px1 = max(0, px1)
                    py1 = max(0, py1)

                    px2 = min(
                        frame.shape[1],
                        px2
                    )

                    py2 = min(
                        frame.shape[0],
                        py2
                    )


                    # -------------------------
                    # metadata
                    # -------------------------

                    box_width = max(0, px2 - px1)
                    box_height = max(0, py2 - py1)

                    frame_h, frame_w = frame.shape[:2]

                    box_area = box_width * box_height
                    frame_area = frame_w * frame_h

                    area_ratio = (
                        box_area / frame_area
                        if frame_area > 0
                        else 0
                    )

                    left_margin = px1 / frame_w
                    right_margin = (frame_w - px2) / frame_w

                    top_margin = py1 / frame_h
                    bottom_margin = (frame_h - py2) / frame_h


                    # -------------------------
                    # overlap with other people
                    # -------------------------

                    max_other_iou = 0.0

                    for other_box, other_track_id in zip(
                        boxes,
                        track_ids
                    ):

                        if other_track_id == track_id:
                            continue

                        ox1, oy1, ox2, oy2 = other_box

                        other_iou = calculate_box_iou(
                            (px1, py1, px2, py2),
                            (ox1, oy1, ox2, oy2)
                        )

                        max_other_iou = max(
                            max_other_iou,
                            other_iou
                        )


                    # ============================================================
                    # REID CROP QUALITY
                    # ============================================================

                    reid_crop_good = (
                        conf >= 0.65
                        and area_ratio >= 0.03
                        and left_margin >= 0.01
                        and right_margin >= 0.01
                        and top_margin >= 0.01
                        and bottom_margin >= 0.01
                        and max_other_iou <= 0.30
                    )


                    # =====================================================
                    # ADD NEW / REAPPEARING TRACK DIAGNOSTIC RIGHT HERE
                    # =====================================================

                    previous_seen = track_last_seen.get(
                        track_id
                    )

                    if track_id not in track_first_seen:

                        track_first_seen[track_id] = frame_counter

               

                        identity_diag(
                            "TRACK_FIRST_SEEN",
                            camera_id=int(camera_id),
                            frame=int(frame_counter),
                            track_id=int(track_id),
                            confidence=float(conf),

                            bbox=[
                                int(px1),
                                int(py1),
                                int(px2),
                                int(py2)
                            ],

                            area_ratio=float(area_ratio),
                            max_other_iou=float(max_other_iou),

                            margins={
                                "left": float(left_margin),
                                "right": float(right_margin),
                                "top": float(top_margin),
                                "bottom": float(bottom_margin)
                            }
                        )

                    elif (
                        previous_seen is not None
                        and frame_counter - previous_seen > 1
                    ):

                        identity_diag(
                            "TRACK_REAPPEARED",
                            camera_id=camera_id,
                            frame=frame_counter,
                            track_id=track_id,
                            gap_frames=(
                                frame_counter
                                - previous_seen
                                - 1
                            )
                        )

                    track_last_seen[track_id] = frame_counter


                    # ============================================================
                    # NEW / UNIDENTIFIED TRACK -> COLLECT REID EVIDENCE
                    # ============================================================

                    if track_id not in track_identity_map:

                        if track_id not in track_reid_crops:
                            track_reid_crops[track_id] = []

                        last_sample_frame = track_reid_last_sample_frame.get(
                            track_id,
                            -REID_SAMPLE_GAP
                        )

                        enough_gap = (
                            frame_counter - last_sample_frame
                            >= REID_SAMPLE_GAP
                        )

                        # --------------------------------------------------------
                        # Collect good crops only.
                        # OSNet does NOT run yet.
                        # dhdhdhdhdh delete comment bc old 
                        # --------------------------------------------------------

                        if enough_gap:

                            crop_state = classify_reid_crop_state(
                                reid_crop_good=reid_crop_good,
                                area_ratio=area_ratio,
                                box_height=box_height,
                                frame_h=frame_h
                            )

                            # ====================================
                            # BAD
                            # Cheap rules already reject it.
                            # NO Pose.
                            # NO OSNet.
                            # ====================================

                            if crop_state == "BAD":

                                track_reid_waiting_clear.add(
                                    track_id
                                )

                            else:

                                person_crop = frame[
                                    py1:py2,
                                    px1:px2
                                ]

                                if (
                                    person_crop is not None
                                    and person_crop.size > 0
                                ):

                                    crop_allowed = False

                                    # ====================================
                                    # CLEAR
                                    # Obviously usable.
                                    # NO Pose.
                                    # ====================================

                                    if crop_state == "CLEAR":

                                        crop_allowed = True

                                    # ====================================
                                    # AMBIGUOUS
                                    # Only HERE do we ask Pose.
                                    # ====================================

                                    else:

                                        # Important:
                                        # don't run Pose again next frame.
                                        # Wait for the normal 5-frame gap.
                                        track_reid_last_sample_frame[
                                            track_id
                                        ] = frame_counter

                                        # Lazy-load Pose only if needed.
                                        if worker_pose is None:

                                            worker_pose = (
                                                PoseLandmarker
                                                .create_from_model_path(
                                                    pose_model_path
                                                )
                                            )

                                        (
                                            crop_allowed,
                                            pose_details
                                        ) = pose_allows_reid_crop(
                                            worker_pose,
                                            person_crop
                                        )

                                        identity_diag(
                                            "REID_POSE_GATE",
                                            camera_id=camera_id,
                                            track_id=track_id,
                                            frame=frame_counter,
                                            crop_state=crop_state,
                                            area_ratio=float(area_ratio),
                                            allowed=bool(crop_allowed),
                                            pose_details=pose_details
                                        )

                                    # ====================================
                                    # Crop accepted for ReID
                                    # ====================================

                                    if crop_allowed:

                                        track_reid_crops[
                                            track_id
                                        ].append(
                                            person_crop.copy()
                                        )

                                        track_reid_last_sample_frame[
                                            track_id
                                        ] = frame_counter

                                        track_reid_waiting_clear.discard(
                                            track_id
                                        )

                                    # ====================================
                                    # Crop rejected
                                    # wait until clearer view
                                    # ====================================

                                    else:

                                        track_reid_waiting_clear.add(
                                            track_id
                                        )

                        # --------------------------------------------------------
                        # Once we have enough crops:
                        # ONE batched OSNet call -> average embeddings
                        # --------------------------------------------------------

                        if (
                            len(track_reid_crops[track_id])
                            >= REID_SAMPLES_NEEDED
                        ):

                            reid_start = time.perf_counter()

                            aggregated_embedding = (
                                get_aggregated_person_embedding(
                                    track_reid_crops[track_id],
                                    camera_id=camera_id,
                                    track_id=track_id
                                )
                            )



                            if aggregated_embedding is not None:

                                candidate_person_id, candidate_similarity = (
                                    find_best_gallery_match(
                                        aggregated_embedding
                                    )
                                )

                                # ------------------------------------------------
                                # NEW:
                                # no existing person passed the threshold
                                # ------------------------------------------------

                                if (
                                    candidate_person_id is None
                                    or candidate_similarity < REID_THRESHOLD
                                ):

                                    reid_result = get_global_person_id(
                                        aggregated_embedding,
                                        camera_id=camera_id,
                                        track_id=track_id
                                    )

                                    if reid_result is not None:

                                        person_id, similarity = reid_result

                                        track_identity_map[
                                            track_id
                                        ] = (
                                            person_id,
                                            similarity
                                        )

                                        track_reid_pending.pop(
                                            track_id,
                                            None
                                        )

                                        identity_diag(
                                            "REID_NEW_CONFIRMED",
                                            camera_id=camera_id,
                                            track_id=track_id,
                                            person_id=person_id,
                                            similarity=float(similarity)
                                        )

                                # ------------------------------------------------
                                # EXISTING PERSON CANDIDATE:
                                # first agreement -> UNCERTAIN
                                # second agreement -> MATCH
                                # ------------------------------------------------

                                else:

                                    pending = track_reid_pending.get(
                                        track_id
                                    )

                                    if (
                                        pending is None
                                        or pending["person_id"]
                                        != candidate_person_id
                                    ):

                                        track_reid_pending[
                                            track_id
                                        ] = {
                                            "person_id": candidate_person_id,
                                            "confirmations": 1,
                                            "first_similarity": candidate_similarity
                                        }

                                        identity_diag(
                                            "REID_UNCERTAIN",
                                            camera_id=camera_id,
                                            track_id=track_id,
                                            candidate_person_id=candidate_person_id,
                                            similarity=float(candidate_similarity),
                                            confirmations=1,
                                            confirmations_needed=REID_CONFIRMATIONS_NEEDED
                                        )

                                    else:

                                        pending[
                                            "confirmations"
                                        ] += 1

                                        identity_diag(
                                            "REID_CONFIRMATION",
                                            camera_id=camera_id,
                                            track_id=track_id,
                                            candidate_person_id=candidate_person_id,
                                            similarity=float(candidate_similarity),
                                            confirmations=pending["confirmations"],
                                            confirmations_needed=REID_CONFIRMATIONS_NEEDED
                                        )

                                        if (
                                            pending["confirmations"]
                                            >= REID_CONFIRMATIONS_NEEDED
                                        ):

                                            reid_result = get_global_person_id(
                                                aggregated_embedding,
                                                camera_id=camera_id,
                                                track_id=track_id
                                            )

                                            if reid_result is not None:

                                                person_id, similarity = reid_result

                                                track_identity_map[
                                                    track_id
                                                ] = (
                                                    person_id,
                                                    similarity
                                                )

                                                track_reid_pending.pop(
                                                    track_id,
                                                    None
                                                )

                                                print(
                                                    f"[TRACK + CONFIRMED REID] "
                                                    f"Camera {camera_id} | "
                                                    f"Track {track_id} -> "
                                                    f"Person {person_id} | "
                                                    f"Similarity {similarity:.3f}"
                                                )

                            total_reid_time += (
                                time.perf_counter()
                                - reid_start
                            )

                            # This batch has been consumed.
                            # If still uncertain, collect a fresh batch of 3 crops.
                            track_reid_crops[
                                track_id
                            ] = []

                            track_reid_last_sample_frame.pop(
                                track_id,
                                None
                            )




                    # ==========================================
                    # EXISTING TRACK -> REUSE REID RESULT
                    # ==========================================

                    person_id, similarity = (
                        track_identity_map.get(
                            track_id,
                            (None, None)
                        )
                    )


                    # ==========================================
                    # LABEL
                    # ==========================================

                    if person_id is not None:

                        label = (
                            f"Person {person_id} "
                            f"| Track {track_id} "
                            f"| YOLO {conf:.2f}"
                        )




                    else:

                        pending = track_reid_pending.get(
                            track_id
                        )

                        if pending is not None:

                            label = (
                                f"Track {track_id} "
                                f"| Uncertain Person {pending['person_id']} "
                                f"| Confirming "
                                f"{pending['confirmations']}/"
                                f"{REID_CONFIRMATIONS_NEEDED}"
                            )


                        else:

                            sample_count = len(
                                track_reid_crops.get(
                                    track_id,
                                    []
                                )
                            )

                            if (
                                track_id
                                in track_reid_waiting_clear
                                and sample_count == 0
                            ):

                                label = (
                                    f"Track {track_id} "
                                    f"| Waiting for clear view"
                                )

                            else:

                                label = (
                                    f"Track {track_id} "
                                    f"| Identifying "
                                    f"{sample_count}/{REID_SAMPLES_NEEDED}"
                                )

                  

                    # ==========================================
                    # DRAW
                    # ==========================================

                    cv2.rectangle(
                        frame,
                        (px1, py1),
                        (px2, py2),
                        (255, 0, 0),
                        2
                    )

                    cv2.putText(
                        frame,
                        label,
                        (
                            px1,
                            max(18, py1 - 10)
                        ),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.45,
                        (255, 0, 0),
                        2
                    )

                # =====================================================
                # SAME-CAMERA PERSON-ID CONFLICT DIAGNOSTIC
                # OUTSIDE the person loop
                # =====================================================

                person_to_tracks = {}

                for active_track_id in current_active_tracks:

                    mapped = track_identity_map.get(
                        active_track_id
                    )

                    if not mapped:
                        continue

                    person_id = mapped[0]

                    if person_id is None:
                        continue

                    person_to_tracks.setdefault(
                        person_id,
                        []
                    ).append(active_track_id)


                current_person_conflicts = set()

                for person_id, person_tracks in person_to_tracks.items():

                    if len(person_tracks) > 1:

                        conflict_key = (
                            person_id,
                            tuple(sorted(person_tracks))
                        )

                        current_person_conflicts.add(
                            conflict_key
                        )

                        # Only save when this conflict FIRST appears
                        if conflict_key not in previous_person_conflicts:

                            identity_diag(
                                "SAME_CAMERA_PERSON_CONFLICT",
                                camera_id=camera_id,
                                frame=frame_counter,
                                person_id=person_id,
                                track_ids=sorted(person_tracks)
                            )

                previous_person_conflicts = current_person_conflicts
      
            ''' OLD CODE
            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            hand_results = worker_hands.process(
                rgb
            )

            detected_hands = (
                hand_results.multi_hand_landmarks
                if hand_results.multi_hand_landmarks
                else []
            )
            '''

            #=======================
            #NEW CODE FOR ABOVE 
            #=======================
            hand_start = time.perf_counter()

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            mp_image = mp.Image(
                image_format=mp.ImageFormat.SRGB,
                data=rgb
            )

            timestamp_ms = int(time.monotonic() * 1000)

            hand_results = worker_hands.detect_for_video(
                mp_image,
                timestamp_ms
            )

            total_hand_time += (
                time.perf_counter() - hand_start
            )

            detected_hands = (
                hand_results.hand_landmarks
                if hand_results.hand_landmarks
                else []
            )

            for hand in detected_hands:
                draw_hand_landmarks(
                    frame,
                    hand
                )

        

            # =========================
            # MEDIAPIPE HEAD POSE
            # =========================


            face_results = worker_face_mesh.detect_for_video(
                mp_image,
                timestamp_ms
            )


            if face_results.face_landmarks:

                face_landmarks = face_results.face_landmarks[0]

                head_pose = calculate_head_pose(
                    face_landmarks,
                    frame
                )

                if head_pose is not None:

                    yaw = head_pose["yaw"]
                    pitch = head_pose["pitch"]

                    # Collect neutral calibration measurements
                    if neutral_pitch is None:

                        head_calibration_samples.append(
                            (yaw, pitch)
                        )

                        if len(head_calibration_samples) >= HEAD_CALIBRATION_FRAMES:

                            neutral_yaw = float(np.median([
                                sample[0]
                                for sample in head_calibration_samples
                            ]))

                            neutral_pitch = float(np.median([
                                sample[1]
                                for sample in head_calibration_samples
                            ]))

                            print(
                                f"[HEAD CALIBRATION] "
                                f"Yaw={neutral_yaw:.1f}, "
                                f"Pitch={neutral_pitch:.1f}"
                            )

                    # Classify direction relative to neutral
                    if neutral_pitch is not None:

                        yaw_diff = yaw - neutral_yaw
                        pitch_diff = pitch - neutral_pitch

                        
                        if yaw_diff < -HEAD_YAW_THRESHOLD:
                            direction = "Looking Left"

                        elif yaw_diff > HEAD_YAW_THRESHOLD:
                            direction = "Looking Right"

                        elif pitch_diff > HEAD_DOWN_THRESHOLD:
                            direction = "Looking Down"

                        elif pitch_diff < -HEAD_UP_THRESHOLD:
                            direction = "Looking Up"

                        else:
                            direction = "Looking Forward"
                        
                        


                        head_pose["direction"] = direction
                        head_pose["yaw_diff"] = yaw_diff
                        head_pose["pitch_diff"] = pitch_diff    



            current_hand_inside = any(
                hand_inside_roi(
                    hand,
                    frame,
                    current_roi
                )
                for hand in detected_hands
            )

            now = time.monotonic()

            if current_hand_inside:

                if hand_interaction_start is None:
                    hand_interaction_start = now
                    hand_alerted_levels.clear()

                hand_last_seen = now
                hand_lost_since = None

            else:

                if (
                    hand_interaction_start is not None
                    and hand_lost_since is None
                ):
                    hand_lost_since = now


            #if hand_interaction_start is not None:
            if ENABLE_HAND_ALERTS and hand_interaction_start is not None:

                hand_still_active = (
                    current_hand_inside
                    or (
                        hand_last_seen is not None
                        and now - hand_last_seen <= HAND_LOST_GRACE
                    )
                )

                if hand_still_active:

                    duration = (
                        now - hand_interaction_start
                    )

                    if duration >= HAND_HIGH_TIME_LIMIT:

                        threat_level = "High"
                        level = 3

                    elif duration >= HAND_MEDIUM_TIME_LIMIT:

                        threat_level = "Medium"
                        level = 2

                    else:

                        threat_level = "Low"
                        level = 1


                    if threat_level not in hand_alerted_levels:

                        hand_alerted_levels.add(
                            threat_level
                        )

                        timestamp = int(
                            time.time()
                        )

                       
                        filename = (
                            f"snapshots/camera_{camera_id}_{timestamp}.jpg"
                        )

                        clip_filename = (
                            f"clips/camera_{camera_id}_{timestamp}.mp4"
                        )

                        cv2.imwrite(
                            filename,
                            frame
                        )

                        threading.Thread(
                            target=record_clip,
                            args=(
                                source,
                                clip_filename
                            )
                        ).start()

                        reason = (
                            f"Hand entered ROI - "
                            f"{int(duration)} sec"
                        )

                        alert_id = create_alert(
                            level=level,
                            threat_level=threat_level,
                            snapshot_path=filename,
                            clip_path=clip_filename,
                            reason=reason,
                            camera_id=camera_id
                        )

                        if level == 3 and not sms_sent:

                            users = get_security_fields()

                            for user_id, phone in users:

                                if phone:

                                    phone = normalize_saudi_number(
                                        phone
                                    )

                                    message = (
                                        "Level 3 Alert: High threat detected. "
                                        "Immediate attention required."
                                    )

                                    try:

                                        send_sms_gateway(
                                            phone,
                                            message
                                        )

                                        sms_sent = True

                                        log_sms(
                                            alert_id,
                                            user_id,
                                            message
                                        )

                                    except Exception as e:

                                        print(
                                            "SMS sending failed:",
                                            e
                                        )


                if (
                    hand_lost_since is not None
                    and now - hand_lost_since >= HAND_LOST_GRACE
                ):

                    hand_interaction_start = None
                    hand_last_seen = None
                    hand_lost_since = None
                    hand_alerted_levels.clear()


        '''
        _, buffer = cv2.imencode(
            '.jpg',
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 60]
        )
        '''



        # =========================
        # ROI HEAD ATTENTION TEST
        # =========================

        roi_facing = False
        head_roi_duration = 0.0

        if (
            current_roi is not None
            and head_pose is not None
            and face_landmarks is not None
            and head_pose["direction"] != "Calibrating..."
        ):

            roi_facing = head_looks_toward_roi(
                head_pose,
                face_landmarks,
                frame,
                current_roi
            )

        if roi_facing:

            if head_roi_start is None:
                head_roi_start = time.monotonic()

            head_roi_duration = (
                time.monotonic() - head_roi_start
            )

        else:
            head_roi_start = None

        if head_roi_duration >= HEAD_HIGH_TIME_LIMIT:
            head_roi_level = "HIGH"

        elif head_roi_duration >= HEAD_MEDIUM_TIME_LIMIT:
            head_roi_level = "MEDIUM"

        elif roi_facing:
            head_roi_level = "LOW"

        else:
            head_roi_level = "NONE"



        # =========================
        # DISPLAY HEAD POSE
        # =========================

        if head_pose:


            cv2.putText(
                frame,
                head_pose["direction"],
                (10, 25),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 255),
                2
            )

            if neutral_pitch is not None:

                cv2.putText(
                    frame,
                    f"Yaw diff: {head_pose['yaw_diff']:.1f}",
                    (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 255, 255),
                    1
                )

                #===============================
                #head orinetation debugging
                #================================
                cv2.putText(
                    frame,
                    f"Pitch diff: {head_pose['pitch_diff']:.1f}",
                    (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.4,
                    (0, 255, 255),
                    1
                )


                # =========================
                # DISPLAY ROI ATTENTION
                # =========================

                cv2.putText(
                    frame,
                    f"Toward ROI: {'YES' if roi_facing else 'NO'}",
                    (10, 95),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 0) if roi_facing else (0, 0, 255),
                    2
                )

                cv2.putText(
                    frame,
                    f"Attention: {head_roi_duration:.1f}s",
                    (10, 115),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2
                )

                cv2.putText(
                    frame,
                    f"Head attention: {head_roi_level}",
                    (10, 135),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (0, 255, 255),
                    2
                )

           




        # ============================================================
        # PERFORMANCE TEST - ENCODE TIME - DELETE LATER
        # ============================================================

        encode_start = time.perf_counter()

        _, buffer = cv2.imencode(
            '.jpg',
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 60]
        )

        encode_time = time.perf_counter() - encode_start
        total_encode_time += encode_time

        # ============================================================
        # END PERFORMANCE TEST - ENCODE TIME - DELETE LATER
        # ============================================================


        # ============================================================
        # PERFORMANCE TEST - CALCULATE + PRINT RESULTS - DELETE LATER
        # ============================================================

        perf_frame_count += 1

        elapsed = time.time() - perf_start_time

        if elapsed >= 1.0:

            current_fps = perf_frame_count / elapsed

            avg_read_ms = (
                total_read_time / perf_frame_count
            ) * 1000

            avg_yolo_ms = (
                total_yolo_time / perf_frame_count
            ) * 1000

            avg_reid_ms = (
                total_reid_time / perf_frame_count
            ) * 1000

            avg_hand_ms = (
                total_hand_time / perf_frame_count
            ) * 1000

            avg_encode_ms = (
                total_encode_time / perf_frame_count
            ) * 1000

            camera_type_name = (
                "USB"
                if isinstance(source, int)
                else "IP"
            )

            print(
                f"[PERFORMANCE] "
                f"{camera_type_name} | "
                f"FPS: {current_fps:.2f} | "
                f"Read: {avg_read_ms:.1f} ms | "
                f"YOLO+Track: {avg_yolo_ms:.1f} ms | "
                f"ReID: {avg_reid_ms:.1f} ms | "
                f"Hand: {avg_hand_ms:.1f} ms | "
                f"Encode: {avg_encode_ms:.1f} ms"
            )

            perf_start_time = time.time()
            perf_frame_count = 0

            total_read_time = 0
            total_yolo_time = 0
            total_reid_time = 0
            total_hand_time = 0
            total_encode_time = 0

        # ============================================================
        # END PERFORMANCE TEST - CALCULATE + PRINT RESULTS - DELETE LATER
        # ============================================================

        frame = buffer.tobytes()

       

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n'
            + frame +
            b'\r\n'
        )

    worker_hands.close()


    worker_face_mesh.close()

    if worker_pose is not None:
        worker_pose.close()

    cap.release()


def normalize_saudi_number(phone: str):

    phone = phone.strip()

    if phone.startswith("+966"):
        return phone

    if phone.startswith("0"):
        return "+966" + phone[1:]

    if phone.startswith("966"):
        return "+" + phone

    return phone