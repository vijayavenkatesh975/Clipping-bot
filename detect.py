"""
Facecam Detection and Mode Classifier (Streamer vs Normal Video)
Uses OpenCV YuNet DNN face detection with automatic fallback.
"""
import glob
import os
import subprocess
import numpy as np
import cv2

YUNET_MODEL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models", "face_detection_yunet_2023mar.onnx")


def get_detector(w, h):
    """Initializes OpenCV YuNet face detector for given frame dimensions."""
    if os.path.exists(YUNET_MODEL):
        try:
            return cv2.FaceDetectorYN.create(YUNET_MODEL, "", (w, h), score_threshold=0.6, nms_threshold=0.3)
        except Exception as ex:
            print(f"[detect] YuNet initialization failed: {ex}")
    return None


def extract_sample_frames(video_paths, max_frames=12, temp_dir=None):
    """
    Extracts evenly spaced sample frames from the downloaded video segment(s).
    """
    if not temp_dir:
        temp_dir = os.path.dirname(video_paths[0]) if video_paths else "."

    frames = []
    for vid in video_paths:
        cap = cv2.VideoCapture(vid)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if total <= 0:
            cap.release()
            continue

        step = max(1, total // (max_frames // len(video_paths) + 1))
        idx = 0
        while cap.isOpened() and len(frames) < max_frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ret, frame = cap.read()
            if not ret or frame is None:
                break
            frames.append(frame)
            idx += step
        cap.release()

    return frames


def cluster_faces(detected_faces, max_dist=0.08):
    """
    Clusters detected face boxes by spatial center distance.
    In a livestream, in-game characters move around or appear briefly,
    while the streamer's facecam stays pinned to the exact same position!
    """
    clusters = []
    for f in detected_faces:
        cx = f[0] + f[2] / 2.0
        cy = f[1] + f[3] / 2.0
        matched = False
        for c in clusters:
            avg_cx = np.mean([x[0] + x[2] / 2.0 for x in c])
            avg_cy = np.mean([x[1] + x[3] / 2.0 for x in c])
            dist = np.sqrt((cx - avg_cx) ** 2 + (cy - avg_cy) ** 2)
            if dist < max_dist:
                c.append(f)
                matched = True
                break
        if not matched:
            clusters.append([f])
    return clusters


def detect_facecam(video_paths, out_preview_path=None):
    """
    Analyzes sample frames from downloaded segments.
    Returns:
      is_streamer: bool
      facecam_box: (fx, fy, fw, fh) as fractions (0.0 - 1.0)
      preview_path: str or None
    """
    frames = extract_sample_frames(video_paths, max_frames=12)
    if not frames:
        return False, (0.0, 0.0, 0.0, 0.0), None

    h, w = frames[0].shape[:2]
    detector = get_detector(w, h)
    if not detector:
        print("[detect] No face detector model available; defaulting to normal mode.")
        return False, (0.0, 0.0, 0.0, 0.0), None

    detected_faces = []
    frame_with_face = None
    best_face = None

    for frame in frames:
        detector.setInputSize((w, h))
        _, faces = detector.detect(frame)
        if faces is not None and len(faces) > 0:
            for f in faces:
                fx, fy, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
                conf = float(f[-1])
                # Filter out tiny noise/specks: real streamer faces are at least 4.5% of frame height
                if conf >= 0.65 and (fh / h) >= 0.045:
                    detected_faces.append((fx / w, fy / h, fw / w, fh / h))
                    if frame_with_face is None or conf > (best_face[-1] if best_face is not None else 0):
                        frame_with_face = frame.copy()
                        best_face = f

    total_sampled = len(frames)
    print(f"[detect] Total face detections: {len(detected_faces)} across {total_sampled} frames")

    if not detected_faces:
        print("[detect] Normal Mode: No faces detected in sampled frames.")
        return False, (0.0, 0.0, 0.0, 0.0), None

    # Spatial clustering: find stable static facecam overlay
    clusters = cluster_faces(detected_faces, max_dist=0.08)
    print(f"[detect] Found {len(clusters)} spatial face clusters.")

    streamer_cluster = None
    for idx, c in enumerate(clusters, 1):
        c_boxes = np.array(c)
        count = len(c)
        med_x, med_y, med_w, med_h = np.median(c_boxes, axis=0)
        cen_x = med_x + med_w / 2.0
        cen_y = med_y + med_h / 2.0
        area = med_w * med_h
        std_x = float(np.std(c_boxes[:, 0] + c_boxes[:, 2] / 2.0)) if count > 1 else 0.0
        std_y = float(np.std(c_boxes[:, 1] + c_boxes[:, 3] / 2.0)) if count > 1 else 0.0
        is_edge = (cen_x < 0.35 or cen_x > 0.65 or cen_y < 0.35 or cen_y > 0.65)

        print(f"  Cluster #{idx}: count={count}, area={area:.4f}, cen=({cen_x:.3f}, {cen_y:.3f}), std=({std_x:.4f}, {std_y:.4f}), is_edge={is_edge}")

        # Streamer Facecam Criteria:
        # Appears across >= 3 frames, small box (area <= 12%), ultra-stable (std < 0.04), located near edge/corner
        if count >= 3 and area <= 0.12 and std_x < 0.04 and std_y < 0.04 and is_edge:
            streamer_cluster = c_boxes
            break

    if streamer_cluster is None:
        print("[detect] Normal Mode: No static facecam overlay found.")
        return False, (0.0, 0.0, 0.0, 0.0), None

    # Compute facecam crop from the static cluster in true pixel coordinates
    # Slot aspect ratio for top pane is 1080 / 640 = 1.6875
    slot_aspect = 1080.0 / 640.0
    med_x, med_y, med_w, med_h = np.median(streamer_cluster, axis=0)

    face_cx_px = (med_x + med_w / 2.0) * float(w)
    face_cy_px = (med_y + med_h / 2.0) * float(h)
    face_h_px = med_h * float(h)

    # Frame the face comfortably with room for shoulders, microphone, and background
    desired_h_px = max(face_h_px * 1.9, float(h) * 0.16)
    desired_w_px = desired_h_px * slot_aspect

    # Distance to nearest horizontal edge to guarantee dead-center positioning without clipping
    dist_to_edge_x = min(face_cx_px, float(w) - face_cx_px)
    max_w_px = max(100.0, 2.0 * (dist_to_edge_x - 10.0))

    if desired_w_px > max_w_px:
        crop_w_px = max_w_px
        crop_h_px = crop_w_px / slot_aspect
    else:
        crop_w_px = desired_w_px
        crop_h_px = desired_h_px

    crop_x_px = max(0.0, min(float(w) - crop_w_px, face_cx_px - crop_w_px / 2.0))
    crop_y_px = max(0.0, min(float(h) - crop_h_px, face_cy_px - crop_h_px * 0.50))

    crop_x = crop_x_px / float(w)
    crop_y = crop_y_px / float(h)
    expand_w = crop_w_px / float(w)
    expand_h = crop_h_px / float(h)

    final_crop = (round(float(crop_x), 4), round(float(crop_y), 4), round(float(expand_w), 4), round(float(expand_h), 4))
    print(f"[detect] STREAMER MODE CONFIRMED! Facecam crop: {final_crop}")

    # Generate preview image if requested
    preview_file = None
    if out_preview_path and frame_with_face is not None:
        px = int(crop_x * w)
        py = int(crop_y * h)
        pw = int(expand_w * w)
        ph = int(expand_h * h)
        cv2.rectangle(frame_with_face, (px, py), (px + pw, py + ph), (0, 255, 0), 4)
        cv2.putText(frame_with_face, "FACECAM DETECTED", (px + 10, max(30, py + 35)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 2)
        os.makedirs(os.path.dirname(os.path.abspath(out_preview_path)), exist_ok=True)
        cv2.imwrite(out_preview_path, frame_with_face)
        preview_file = out_preview_path

    return True, final_crop, preview_file
