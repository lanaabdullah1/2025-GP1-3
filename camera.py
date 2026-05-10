import cv2
import time
import os
import threading


from model.query import (
    create_alert,
    get_security_fields,
    log_sms,
    send_sms
)

roi = None
roi_version = 0

prev_frame = None

stream_id = 0

camera_source = None

last_alert_time = {}

ALERT_COOLDOWN = 15




def set_roi(x1, y1, x2, y2):
    global roi
    global roi_version

    roi = (
        int(x1),
        int(y1),
        int(x2),
        int(y2)
    )

    roi_version += 1


def reset_roi():
    global roi
    global prev_frame
    global roi_version
    global stream_id

    roi = None

    prev_frame = None

    roi_version += 1

    stream_id += 1


def set_camera(src):
    global camera_source

    camera_source = src


def get_camera():
    return camera_source


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


def generate_frames(source, camera_id=1):

    global prev_frame
    global roi
    global roi_version
    global stream_id

    cap = cv2.VideoCapture(source)

    if not os.path.exists("snapshots"):
        os.makedirs("snapshots")

    if not os.path.exists("clips"):
        os.makedirs("clips")

    local_version = roi_version

    local_stream = stream_id

    

    while True:

        if local_stream != stream_id:
            break

        success, frame = cap.read()

        if not success:
            break

        

       

      

        frame = cv2.resize(
            frame,
            (480, 270)
        )

     
       
       

        if local_version != roi_version:

            prev_frame = None

            local_version = roi_version

        h, w = frame.shape[:2]

        if roi:

            x1, y1, x2, y2 = roi

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

            if x2 > x1 and y2 > y1:

                roi_frame = frame[y1:y2, x1:x2]

                gray = cv2.cvtColor(
                    roi_frame,
                    cv2.COLOR_BGR2GRAY
                )

                blur = cv2.GaussianBlur(
                    gray,
                    (9, 9),
                    0
                )

                if prev_frame is None:

                    prev_frame = blur

                    continue

                diff = cv2.absdiff(
                    prev_frame,
                    blur
                )

                _, thresh = cv2.threshold(
                    diff,
                    25,
                    255,
                    cv2.THRESH_BINARY
                )

                thresh = cv2.dilate(
                    thresh,
                    None,
                    iterations=2
                )

                contours = cv2.findContours(
                    thresh,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE
                )

                contours = (
                    contours[0]
                    if len(contours) == 2
                    else contours[1]
                )

                for contour in contours:

                    area = cv2.contourArea(contour)

                    if area < 1500:
                        continue

                    if area < 5000:

                        threat_level = "Low"

                        level = 1

                    elif area < 15000:

                        threat_level = "Medium"

                        level = 2

                    else:

                        threat_level = "High"

                        level = 3

                    now = time.time()

                    last_time = last_alert_time.get(
                        camera_id,
                        0
                    )

                    if now - last_time < ALERT_COOLDOWN:
                        continue

                   

                    last_alert_time[camera_id] = now

                    timestamp = int(time.time())

                    filename = (
                        f"snapshots/{timestamp}.jpg"
                    )

                    clip_filename = (
                        f"clips/{timestamp}.avi"
                    )

                   

                    cv2.imwrite(
                        filename,
                        frame
                    )

                    

            

                    threading.Thread(
                        target=record_clip,
                        args=(source, clip_filename)
                    ).start()

                    reason = (
                        f"{threat_level} motion detected"
                    )

                    alert_id = create_alert(
                        level=level,
                        threat_level=threat_level,
                        snapshot_path=filename,
                        clip_path=clip_filename,
                        reason=reason,
                        camera_id=camera_id
                    )

                   

                    users = get_security_fields()

                    for user_id, phone in users:

                        if phone:

                            phone = normalize_saudi_number(
                                phone
                            )

                            log_sms(
                                alert_id,
                                user_id,
                                reason
                            )

                prev_frame = blur

        _, buffer = cv2.imencode(
            '.jpg',
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 60]
        )

        frame = buffer.tobytes()

       

        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n'
            + frame +
            b'\r\n'
        )

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