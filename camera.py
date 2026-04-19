import cv2
import time
import os
from model.query import create_alert, get_security_fields, log_sms,send_sms

roi = None
roi_version = 0
prev_frame = None
last_capture = 0
stream_id = 0


def set_roi(x1, y1, x2, y2):
    global roi, roi_version
    roi = (int(x1), int(y1), int(x2), int(y2))
    roi_version += 1


def reset_roi():
    global roi, prev_frame, roi_version, stream_id
    roi = None
    prev_frame = None
    roi_version += 1
    stream_id += 1

camera_source = None

def set_camera(src):
    global camera_source
    camera_source = src

def get_camera():
    return camera_source

def generate_frames(source):
    global prev_frame, last_capture, roi, roi_version, stream_id

    cap = cv2.VideoCapture(source)

    if not os.path.exists("snapshots"):
        os.makedirs("snapshots")

    local_version = roi_version
    local_stream = stream_id

    while True:
        if local_stream != stream_id:
            break

        success, frame = cap.read()
        if not success:
            break

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

            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

            if x2 > x1 and y2 > y1:
                roi_frame = frame[y1:y2, x1:x2]

                gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
                blur = cv2.GaussianBlur(gray, (21, 21), 0)

                if prev_frame is None:
                    prev_frame = blur

                diff = cv2.absdiff(prev_frame, blur)
                _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
                thresh = cv2.dilate(thresh, None, iterations=2)

                motion = cv2.countNonZero(thresh)

                if 2000 < motion < 50000:
                    if time.time() - last_capture > 5:
                        filename = f"snapshots/{int(time.time())}.jpg"
                        cv2.imwrite(filename, frame)

                        alert_id = create_alert(
                            level=2,
                            snapshot_path=filename,
                            reason="Motion detected",
                            camera_id=1
                        )

                        users = get_security_fields()

                        for user_id, phone in users:
                            if phone:
                                phone = normalize_saudi_number(phone) 
                                #send_sms(phone, "Motion detected")
                                log_sms(alert_id, user_id, "Motion detected")

                        last_capture = time.time()

                prev_frame = blur

        _, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()

        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    cap.release()
    
def normalize_saudi_number(phone: str) -> str:
        phone = phone.strip()

        if phone.startswith("+966"):
            return phone

        if phone.startswith("0"):
            return "+966" + phone[1:]

        # fallback (assume missing +)
        if phone.startswith("966"):
            return "+" + phone

        return phone    