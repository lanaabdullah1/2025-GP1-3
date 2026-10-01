import cv2
import time
import os
import threading

import mediapipe as mp

from ultralytics import YOLO


import torch
import torch.nn.functional as F

from pi_torchreid.utils import FeatureExtractor


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

camera_source = None

last_alert_time = {}

camera_last_frame_time = {}


ALERT_COOLDOWN = 15


HAND_MEDIUM_TIME_LIMIT = 3
HAND_HIGH_TIME_LIMIT = 5
HAND_LOST_GRACE = 3.0

# for to turn off alerts for now
ENABLE_HAND_ALERTS = False

#old ver
#mp_hands = mp.solutions.hands

#new ver
BaseOptions = mp.tasks.BaseOptions
HandLandmarker = mp.tasks.vision.HandLandmarker
HandLandmarkerOptions = mp.tasks.vision.HandLandmarkerOptions
VisionRunningMode = mp.tasks.vision.RunningMode

yolo_model = YOLO("yolov8n.pt")
yolo_lock = threading.Lock()

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

    fourcc = cv2.VideoWriter_fourcc(*'XVID')

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


def get_person_embedding(person_crop):

    if (
        person_crop is None
        or person_crop.size == 0
    ):
        return None

    try:

        # Torchreid expects RGB
        crop_rgb = cv2.cvtColor(
            person_crop,
            cv2.COLOR_BGR2RGB
        )

        with reid_lock:

            features = reid_extractor(
                [crop_rgb]
            )

        embedding = features[0]

        embedding = F.normalize(
            embedding,
            p=2,
            dim=0
        )

        return embedding.cpu()

    except Exception as e:

        print(
            "[REID] Embedding error:",
            e
        )

        return None


def get_global_person_id(embedding):

    global next_person_id

    if embedding is None:
        return None

    best_person_id = None
    best_similarity = -1.0

    with gallery_lock:

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

            # Compare with the best previous view
            person_similarity = max(similarities)

            if person_similarity > best_similarity:

                best_similarity = person_similarity
                best_person_id = person_id


        print(
            f"[REID DEBUG] best ID={best_person_id}, "
            f"similarity={best_similarity:.3f}, "
            f"threshold={REID_THRESHOLD}"
        )

        # Existing person
        if (
            best_person_id is not None
            and best_similarity >= REID_THRESHOLD
        ):

            person_gallery[
                best_person_id
            ].append(embedding)

            # Keep only latest few observations
            person_gallery[
                best_person_id
            ] = person_gallery[
                best_person_id
            ][-MAX_EMBEDDINGS_PER_PERSON:]

            return (
                best_person_id,
                best_similarity
            )

        # New person
        person_id = next_person_id
        next_person_id += 1

        person_gallery[
            person_id
        ] = [embedding]

        return (
            person_id,
            1.0
        )


def generate_frames(source, camera_id=1):

   
    global camera_last_frame_time
    global sms_sent

    state = get_camera_state(camera_id)

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

            local_version = state["roi_version"]

        h, w = frame.shape[:2]

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

            detected_persons = []

            '''
            with yolo_lock:

                yolo_results = yolo_model(
                    frame,
                    imgsz=320,
                    verbose=False
                )
            '''

            # ============================================================
            # PERFORMANCE TEST - YOLO TIME - DELETE LATER
            # ============================================================

            yolo_start = time.perf_counter()

            with yolo_lock:

                yolo_results = yolo_model(
                    frame,
                    imgsz=320,
                    verbose=False
                )

            yolo_time = time.perf_counter() - yolo_start
            total_yolo_time += yolo_time

            # ============================================================
            # END PERFORMANCE TEST - YOLO TIME - DELETE LATER
            # ============================================================




            for result in yolo_results:

                for box in result.boxes:

                    cls = int(box.cls[0])
                    conf = float(box.conf[0])

                    # COCO class 0 = person
                    if cls != 0:
                        continue

                    if conf < 0.65:
                        continue

                    px1, py1, px2, py2 = map(
                        int,
                        box.xyxy[0]
                    )

                    person = (
                        px1,
                        py1,
                        px2,
                        py2,
                        conf
                    )

                    '''
                    if person_inside_roi(
                        person,
                        current_roi
                    ):
                        detected_persons.append(
                            person
                        )
                    '''

                    detected_persons.append(
                        person
                    )




            '''
            for person in detected_persons:

                px1, py1, px2, py2, conf = person

                cv2.rectangle(
                    frame,
                    (px1, py1),
                    (px2, py2),
                    (255, 0, 0),
                    2
                )

                cv2.putText(
                    frame,
                    f"Person {conf:.2f}",
                    (px1, max(18, py1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.5,
                    (255, 0, 0),
                    2
                ) 
                '''

            for person in detected_persons:

                px1, py1, px2, py2, conf = person

                # Make sure coordinates stay inside frame
                px1 = max(0, px1)
                py1 = max(0, py1)
                px2 = min(frame.shape[1], px2)
                py2 = min(frame.shape[0], py2)

                # =========================
                # CROP PERSON
                # =========================

                person_crop = frame[
                    py1:py2,
                    px1:px2
                ]

                # =========================
                # RE-ID EMBEDDING
                # =========================

                reid_start = time.perf_counter()

                embedding = get_person_embedding(
                    person_crop
                )

                # =========================
                # GLOBAL PERSON ID
                # =========================

                reid_result = get_global_person_id(
                    embedding
                )

                total_reid_time += (
                    time.perf_counter() - reid_start
                )

                if reid_result is not None:

                    person_id, similarity = reid_result

                    label = (
                        f"Person {person_id} "
                        f"| YOLO {conf:.2f} "
                        f"| ReID {similarity:.2f}"
                    )

                else:

                    label = (
                        f"Person ? "
                        f"| YOLO {conf:.2f}"
                    )

                # =========================
                # DRAW
                # =========================

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
                    (px1, max(18, py1 - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.45,
                    (255, 0, 0),
                    2
                )           


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
                            f"clips/camera_{camera_id}_{timestamp}.avi"
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
                f"YOLO: {avg_yolo_ms:.1f} ms | "
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