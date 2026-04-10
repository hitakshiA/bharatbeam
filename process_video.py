"""
BharatBeam Video Processing Pipeline
=====================================
Processes dashcam footage through YOLO + brightness blob detection,
computes 12-segment adaptive beam states, and logs EVERYTHING per-frame
to JSON for frontend simulation playback.

Output:
  - frame_data.json: per-frame detections, beam states, CAN messages, metrics
  - processed_video.mp4: annotated video with detection overlays
  - segments_timeline.json: lightweight timeline for quick frontend scrubbing

Usage:
  python process_video.py --input raw_footage.mp4 --output output/
"""

import cv2
import numpy as np
import json
import time
import argparse
import os
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Tuple
from ultralytics import YOLO

# ============================================================
# CONFIG
# ============================================================

NUM_SEGMENTS = 12
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720

# Road zone: includes where distant headlights appear (they sit higher than road surface)
# Top: 48% — distant oncoming headlights appear at ~y=340 (47%)
# Bottom: exclude dashcam text bar AND hood reflections
ROAD_ZONE_TOP = int(FRAME_HEIGHT * 0.48)
ROAD_ZONE_BOTTOM = FRAME_HEIGHT - 80  # exclude dashcam text bar + hood reflections

# Hood reflection zone: bottom 20% of frame — ignore ALL detections here
# Also windshield reflections appear in the bottom corners
HOOD_ZONE_TOP = int(FRAME_HEIGHT * 0.80)

# Edge margin: ignore blobs within this many pixels of frame left/right edges
# (windshield reflections and lens flare artifacts appear at frame edges)
EDGE_MARGIN_X = 50

# Segment boundaries (12 equal vertical slices across frame width)
SEGMENT_WIDTH = FRAME_WIDTH // NUM_SEGMENTS

# Brightness blob detection thresholds
BLOB_MIN_BRIGHTNESS = 220  # dashcam auto-exposure compresses brightness — 220 catches real headlights
BLOB_MIN_AREA = 50  # larger minimum to skip tiny noise pixels
BLOB_MAX_AREA = 8000  # smaller max — giant glare blooms are not individual headlights
BLOB_MIN_PEAK = 245  # peak pixel must be near-saturated (real headlights hit 255, dashcam may compress)
BLOB_MIN_MEAN = 190  # mean brightness of blob region — real headlights are uniformly bright, road glow has bright peak but dim surrounds
BLOB_MIN_COMPACTNESS = 0.15  # contour_area / bbox_area — headlights are compact, road glow is sparse

# Beam control parameters
DIM_ONCOMING = 0.08  # PWM duty for segments with oncoming headlights (near-off)
DIM_PRECEDING = 0.35  # PWM duty for segments with preceding taillights
DIM_CLOSE_RANGE = 0.05  # even dimmer when vehicle is very close
HIGHLIGHT_HAZARD = 1.0  # full brightness for hazard highlighting
HIGHLIGHT_PULSE_FRAMES = 8  # frames to hold hazard highlight pulse
DEFAULT_BEAM = 1.0  # full high beam default

# Smooth transition: max change per frame (prevents jarring flicker)
MAX_DIM_RATE = 0.20  # max brightness drop per frame (fast dim)
MAX_BRIGHTEN_RATE = 0.18  # max brightness rise per frame (was 0.08 — too slow, caused stale dims)

# Distance estimation (rough, from vertical position in frame)
# Higher in frame = further away. Adjusted for road zone starting at 48%
CLOSE_RANGE_Y = FRAME_HEIGHT * 0.75  # below this y = close range
MID_RANGE_Y = FRAME_HEIGHT * 0.62
FAR_RANGE_Y = FRAME_HEIGHT * 0.52

# YOLO classes we care about
VEHICLE_CLASSES = {2: 'car', 3: 'motorcycle', 5: 'bus', 7: 'truck'}
HAZARD_CLASSES = {0: 'person', 1: 'bicycle', 15: 'cat', 16: 'dog'}
ALL_CLASSES = {**VEHICLE_CLASSES, **HAZARD_CLASSES}

# Taillight detection (red channel dominant)
TAILLIGHT_RED_MIN = 150
TAILLIGHT_RED_RATIO = 1.5  # red must be this much higher than green and blue


# ============================================================
# DATA STRUCTURES
# ============================================================

@dataclass
class Detection:
    """Single detected object in a frame."""
    det_id: int
    source: str  # 'yolo' or 'blob'
    obj_class: str  # 'car', 'motorcycle', 'headlight', 'taillight', 'person', etc.
    bbox: List[int]  # [x1, y1, x2, y2]
    confidence: float
    center_x: float
    center_y: float
    estimated_distance: str  # 'close', 'mid', 'far'
    segments_affected: List[int]  # which beam segments this detection covers
    is_oncoming: bool  # True = oncoming headlights, False = preceding/hazard
    is_hazard: bool  # True = pedestrian, animal, obstacle


@dataclass
class BeamSegment:
    """State of a single beam segment."""
    segment_id: int
    target_pwm: float  # what controller wants (0.0 - 1.0)
    actual_pwm: float  # after smooth transition
    reason: str  # 'full_beam', 'dim_oncoming', 'dim_preceding', 'hazard_highlight'
    causing_det_ids: List[int]  # which detections caused this state


@dataclass
class CANMessage:
    """Simulated CAN bus message from ADAS ECU to BharatBeam controller."""
    msg_id: str  # hex CAN ID
    timestamp_ms: float
    obj_type: str
    x_position: int  # pixel x mapped to 0-1000 range
    y_position: int  # pixel y mapped to 0-1000 range
    est_distance_m: float
    confidence: float
    segment_target: int


@dataclass
class FrameData:
    """Complete data for a single processed frame."""
    frame_number: int
    timestamp_s: float
    timestamp_ms: float
    speed_kmh: Optional[float]
    gps_lat: Optional[float]
    gps_lon: Optional[float]

    # Detections
    detections: List[Detection] = field(default_factory=list)
    num_vehicles: int = 0
    num_hazards: int = 0
    num_oncoming: int = 0

    # Beam state
    segments: List[BeamSegment] = field(default_factory=list)
    segments_dimmed: int = 0
    segments_full: int = 0
    segments_highlighted: int = 0
    glare_reduction_pct: float = 0.0
    road_illumination_pct: float = 0.0

    # CAN messages generated this frame
    can_messages: List[CANMessage] = field(default_factory=list)

    # Performance
    detection_latency_ms: float = 0.0
    beam_calc_latency_ms: float = 0.0
    total_latency_ms: float = 0.0

    # System mode
    mode: str = 'ADB_ACTIVE'  # ADB_ACTIVE, FULL_HIGH, LOW_BEAM
    active_warnings: List[str] = field(default_factory=list)


# ============================================================
# DETECTION ENGINE
# ============================================================

# Temporal persistence: how many frames a detection must persist to be confirmed
# Reduced from 12 to 5 (~0.4s) — still filters transient flickers, but catches real vehicles fast
# Radius increased to 150px — vehicles shift position as both cars move
PERSIST_FRAMES = 5
PERSIST_RADIUS = 150


class DetectionEngine:
    """Runs YOLO + brightness blob detection on frames."""

    def __init__(self, model_path='yolo11x.pt'):
        print(f"[DetectionEngine] Loading YOLO model: {model_path}")
        self.model = YOLO(model_path)
        self.det_counter = 0

        # Temporal tracking: each tracked object has {cx, cy, age, confirmed}
        self.tracked: List[dict] = []

    def _next_id(self) -> int:
        self.det_counter += 1
        return self.det_counter

    def _estimate_distance(self, cy: float) -> str:
        """Rough distance estimate from vertical position in frame."""
        if cy > CLOSE_RANGE_Y:
            return 'close'
        elif cy > MID_RANGE_Y:
            return 'mid'
        else:
            return 'far'

    def _estimate_distance_meters(self, cy: float) -> float:
        """Rough distance in meters from vertical position."""
        if cy > CLOSE_RANGE_Y:
            return 10.0
        elif cy > MID_RANGE_Y:
            return 30.0
        elif cy > FAR_RANGE_Y:
            return 60.0
        else:
            return 100.0

    def _get_affected_segments(self, x1: int, x2: int, distance: str) -> List[int]:
        """Map bounding box x-range to beam segments, with distance-based spread."""
        seg_start = max(0, x1 // SEGMENT_WIDTH)
        seg_end = min(NUM_SEGMENTS - 1, x2 // SEGMENT_WIDTH)

        # Close range: spread dimming to neighboring segments
        if distance == 'close':
            seg_start = max(0, seg_start - 1)
            seg_end = min(NUM_SEGMENTS - 1, seg_end + 1)

        return list(range(seg_start, seg_end + 1))

    def _in_valid_zone(self, cy: float) -> bool:
        """Check if detection center is in valid road zone (not sky, not hood)."""
        return ROAD_ZONE_TOP <= cy <= ROAD_ZONE_BOTTOM

    def detect_yolo(self, frame: np.ndarray) -> List[Detection]:
        """Run YOLO object detection."""
        results = self.model(frame, conf=0.35, verbose=False)
        detections = []

        for r in results:
            for box in r.boxes:
                cls_id = int(box.cls[0])
                if cls_id not in ALL_CLASSES:
                    continue

                x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2

                # Skip detections in hood reflection zone
                if cy > HOOD_ZONE_TOP:
                    continue

                # Skip detections above road zone (streetlights, sky)
                if cy < ROAD_ZONE_TOP and cls_id in VEHICLE_CLASSES:
                    continue

                # Skip extreme edge detections (windshield artifacts)
                if cx < EDGE_MARGIN_X or cx > FRAME_WIDTH - EDGE_MARGIN_X:
                    continue

                conf = float(box.conf[0])
                obj_class = ALL_CLASSES[cls_id]
                distance = self._estimate_distance(cy)
                is_hazard = cls_id in HAZARD_CLASSES
                is_oncoming = not is_hazard

                detections.append(Detection(
                    det_id=self._next_id(),
                    source='yolo',
                    obj_class=obj_class,
                    bbox=[x1, y1, x2, y2],
                    confidence=conf,
                    center_x=cx,
                    center_y=cy,
                    estimated_distance=distance,
                    segments_affected=self._get_affected_segments(x1, x2, distance),
                    is_oncoming=is_oncoming,
                    is_hazard=is_hazard,
                ))

        return detections

    def detect_blobs(self, frame: np.ndarray) -> List[Detection]:
        """Detect bright headlight blobs and red taillights via thresholding."""
        detections = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        b_ch, g_ch, r_ch = cv2.split(frame)

        # --- Headlight blobs (bright white/yellow spots) ---
        _, bright_mask = cv2.threshold(gray, BLOB_MIN_BRIGHTNESS, 255, cv2.THRESH_BINARY)

        # Strict zone masking: only road zone, exclude sky AND hood reflections
        bright_mask[:ROAD_ZONE_TOP, :] = 0
        bright_mask[ROAD_ZONE_BOTTOM:, :] = 0
        bright_mask[HOOD_ZONE_TOP:, :] = 0

        # Morphological close to merge nearby blobs (reduces duplicate detections)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
        bright_mask = cv2.morphologyEx(bright_mask, cv2.MORPH_CLOSE, kernel)

        contours, _ = cv2.findContours(bright_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area < BLOB_MIN_AREA or area > BLOB_MAX_AREA:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            cx = x + w / 2
            cy = y + h / 2

            # Skip if in hood zone
            if cy > HOOD_ZONE_TOP:
                continue

            # Skip blobs at extreme left/right edges (windshield reflections, lens flare)
            if cx < EDGE_MARGIN_X or cx > FRAME_WIDTH - EDGE_MARGIN_X:
                continue

            # Skip blobs that are very wide relative to height (horizontal flare streaks)
            if w > 0 and h > 0 and w / h > 5.0:
                continue

            # Compactness check: real headlights are dense, road glow is sparse
            bbox_area = w * h
            compactness = area / bbox_area if bbox_area > 0 else 0
            if compactness < BLOB_MIN_COMPACTNESS:
                continue

            distance = self._estimate_distance(cy)

            blob_region = gray[y:y+h, x:x+w]
            peak_brightness = float(np.max(blob_region)) if blob_region.size > 0 else 200
            mean_brightness = float(np.mean(blob_region)) if blob_region.size > 0 else 200

            # Peak intensity check: real headlights saturate the sensor (255 or near)
            if peak_brightness < BLOB_MIN_PEAK:
                continue

            # Mean brightness check: real headlights are uniformly bright (mean>190)
            # Road glow has a few bright pixels but low mean (125-165)
            if mean_brightness < BLOB_MIN_MEAN:
                continue

            detections.append(Detection(
                det_id=self._next_id(),
                source='blob',
                obj_class='headlight',
                bbox=[x, y, x + w, y + h],
                confidence=min(1.0, mean_brightness / 255.0),
                center_x=cx,
                center_y=cy,
                estimated_distance=distance,
                segments_affected=self._get_affected_segments(x, x + w, distance),
                is_oncoming=True,
                is_hazard=False,
            ))

        # --- Taillight blobs (red dominant spots) ---
        red_dominant = (r_ch.astype(float) > TAILLIGHT_RED_MIN) & \
                       (r_ch.astype(float) > g_ch.astype(float) * TAILLIGHT_RED_RATIO) & \
                       (r_ch.astype(float) > b_ch.astype(float) * TAILLIGHT_RED_RATIO)
        red_mask = (red_dominant * 255).astype(np.uint8)
        red_mask[:ROAD_ZONE_TOP, :] = 0
        red_mask[ROAD_ZONE_BOTTOM:, :] = 0
        red_mask[HOOD_ZONE_TOP:, :] = 0

        # Merge nearby red blobs too
        kernel_small = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (10, 10))
        red_mask = cv2.morphologyEx(red_mask, cv2.MORPH_CLOSE, kernel_small)

        contours_red, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for cnt in contours_red:
            area = cv2.contourArea(cnt)
            if area < 40 or area > 10000:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            cx = x + w / 2
            cy = y + h / 2

            if cy > HOOD_ZONE_TOP:
                continue

            distance = self._estimate_distance(cy)

            detections.append(Detection(
                det_id=self._next_id(),
                source='blob',
                obj_class='taillight',
                bbox=[x, y, x + w, y + h],
                confidence=0.7,
                center_x=cx,
                center_y=cy,
                estimated_distance=distance,
                segments_affected=self._get_affected_segments(x, x + w, distance),
                is_oncoming=False,
                is_hazard=False,
            ))

        return detections

    def _deduplicate_blobs(self, blobs: List[Detection]) -> List[Detection]:
        """Remove blob detections whose centers are within 80px of each other."""
        if len(blobs) <= 1:
            return blobs
        keep = []
        for b in blobs:
            too_close = False
            for k in keep:
                dx = b.center_x - k.center_x
                dy = b.center_y - k.center_y
                if (dx * dx + dy * dy) < 80 * 80:
                    too_close = True
                    break
            if not too_close:
                keep.append(b)
        return keep

    def detect(self, frame: np.ndarray) -> Tuple[List[Detection], float]:
        """Run full detection pipeline. Returns detections and latency in ms."""
        t0 = time.perf_counter()

        yolo_dets = self.detect_yolo(frame)
        blob_dets = self.detect_blobs(frame)

        # Deduplicate blobs among themselves first
        blob_dets = self._deduplicate_blobs(blob_dets)

        # Merge: remove blob detections that overlap with YOLO detections
        merged = list(yolo_dets)
        for blob in blob_dets:
            overlaps = False
            for yolo in yolo_dets:
                bx1, by1, bx2, by2 = blob.bbox
                yx1, yy1, yx2, yy2 = yolo.bbox
                margin = 60  # generous margin — if YOLO found it, trust YOLO
                if (bx1 < yx2 + margin and bx2 > yx1 - margin and
                    by1 < yy2 + margin and by2 > yy1 - margin):
                    overlaps = True
                    break
            # Also check overlap with already-merged blobs
            if not overlaps:
                for existing in merged:
                    if existing.source != 'blob':
                        continue
                    dx = blob.center_x - existing.center_x
                    dy = blob.center_y - existing.center_y
                    if (dx * dx + dy * dy) < 100 * 100:
                        overlaps = True
                        break
            if not overlaps:
                merged.append(blob)

        # ── TEMPORAL PERSISTENCE FILTER ──
        # Update tracked objects: match each merged detection to nearest tracked object
        # Only detections that persist for PERSIST_FRAMES are returned as confirmed
        new_tracked = []
        confirmed = []

        for det in merged:
            # Find closest existing tracked object
            best_match = None
            best_dist = PERSIST_RADIUS + 1
            for tr in self.tracked:
                dx = det.center_x - tr['cx']
                dy = det.center_y - tr['cy']
                dist = (dx * dx + dy * dy) ** 0.5
                if dist < best_dist:
                    best_dist = dist
                    best_match = tr

            if best_match is not None and best_dist <= PERSIST_RADIUS:
                # Existing track — increment age
                best_match['cx'] = det.center_x
                best_match['cy'] = det.center_y
                best_match['age'] += 1
                best_match['missed'] = 0
                best_match['det'] = det
                if best_match['age'] >= PERSIST_FRAMES:
                    confirmed.append(det)
            else:
                # New track — start counting
                new_tracked.append({
                    'cx': det.center_x,
                    'cy': det.center_y,
                    'age': 1,
                    'missed': 0,
                    'det': det,
                })

        # Age out tracks that weren't matched this frame (allow 5 frame gap for flickering)
        for tr in self.tracked:
            if tr.get('missed', 0) is not None:
                tr['missed'] = tr.get('missed', 0) + 1
            if tr['missed'] <= 5:
                new_tracked.append(tr)
            # else: drop — object gone

        self.tracked = new_tracked

        latency_ms = (time.perf_counter() - t0) * 1000
        return confirmed, latency_ms


# ============================================================
# BEAM CONTROLLER
# ============================================================

class BeamController:
    """Simulates the NXP S32K312 beam segment controller."""

    def __init__(self):
        # Current actual PWM state per segment (with smoothing)
        self.current_pwm = [DEFAULT_BEAM] * NUM_SEGMENTS
        # Hazard highlight countdown per segment
        self.highlight_counters = [0] * NUM_SEGMENTS

    def compute_target(self, detections: List[Detection]) -> Tuple[List[BeamSegment], float]:
        """Compute target beam state from detections. Returns segments and latency."""
        t0 = time.perf_counter()

        # Start with all segments at full beam
        target_pwm = [DEFAULT_BEAM] * NUM_SEGMENTS
        reasons = ['full_beam'] * NUM_SEGMENTS
        causing_ids: List[List[int]] = [[] for _ in range(NUM_SEGMENTS)]

        # Apply dimming for each detection
        for det in detections:
            for seg in det.segments_affected:
                if seg < 0 or seg >= NUM_SEGMENTS:
                    continue

                if det.is_hazard:
                    # Hazard: trigger highlight pulse
                    self.highlight_counters[seg] = HIGHLIGHT_PULSE_FRAMES
                    reasons[seg] = 'hazard_highlight'
                    causing_ids[seg].append(det.det_id)

                elif det.is_oncoming and det.obj_class == 'headlight':
                    # Oncoming headlight: dim hard
                    dim_level = DIM_CLOSE_RANGE if det.estimated_distance == 'close' else DIM_ONCOMING
                    if dim_level < target_pwm[seg]:
                        target_pwm[seg] = dim_level
                        reasons[seg] = 'dim_oncoming'
                        causing_ids[seg].append(det.det_id)

                elif det.is_oncoming:
                    # YOLO-detected vehicle: dim
                    dim_level = DIM_CLOSE_RANGE if det.estimated_distance == 'close' else DIM_ONCOMING
                    if det.estimated_distance == 'far':
                        # Progressive dimming for far targets
                        dim_level = 0.4
                    if dim_level < target_pwm[seg]:
                        target_pwm[seg] = dim_level
                        reasons[seg] = 'dim_oncoming'
                        causing_ids[seg].append(det.det_id)

                elif det.obj_class == 'taillight':
                    # Preceding vehicle: lighter dim
                    if DIM_PRECEDING < target_pwm[seg]:
                        target_pwm[seg] = DIM_PRECEDING
                        reasons[seg] = 'dim_preceding'
                        causing_ids[seg].append(det.det_id)

        # Apply hazard highlight counters
        for seg in range(NUM_SEGMENTS):
            if self.highlight_counters[seg] > 0:
                target_pwm[seg] = HIGHLIGHT_HAZARD
                if reasons[seg] == 'full_beam':
                    reasons[seg] = 'hazard_highlight'
                self.highlight_counters[seg] -= 1

        # Smooth transitions
        for seg in range(NUM_SEGMENTS):
            diff = target_pwm[seg] - self.current_pwm[seg]
            if diff < 0:
                # Dimming: fast
                self.current_pwm[seg] = max(
                    target_pwm[seg],
                    self.current_pwm[seg] - MAX_DIM_RATE
                )
            else:
                # Brightening: slower
                self.current_pwm[seg] = min(
                    target_pwm[seg],
                    self.current_pwm[seg] + MAX_BRIGHTEN_RATE
                )

        # Build segment objects
        segments = []
        for seg in range(NUM_SEGMENTS):
            segments.append(BeamSegment(
                segment_id=seg,
                target_pwm=round(target_pwm[seg], 3),
                actual_pwm=round(self.current_pwm[seg], 3),
                reason=reasons[seg],
                causing_det_ids=causing_ids[seg],
            ))

        latency_ms = (time.perf_counter() - t0) * 1000
        return segments, latency_ms


# ============================================================
# CAN MESSAGE GENERATOR
# ============================================================

def generate_can_messages(detections: List[Detection], timestamp_ms: float) -> List[CANMessage]:
    """Generate simulated CAN FD messages for each detection."""
    messages = []
    for det in detections:
        # Map pixel position to 0-1000 range (CAN signal encoding)
        x_pos = int((det.center_x / FRAME_WIDTH) * 1000)
        y_pos = int((det.center_y / FRAME_HEIGHT) * 1000)

        # Distance estimate in meters
        dist_map = {'close': 15.0, 'mid': 40.0, 'far': 80.0}
        est_dist = dist_map.get(det.estimated_distance, 50.0)

        # CAN message ID assignment
        if det.is_oncoming:
            msg_id = '0x1A0'  # ADAS_OBJ_ONCOMING
        elif det.is_hazard:
            msg_id = '0x1A2'  # ADAS_OBJ_HAZARD
        else:
            msg_id = '0x1A1'  # ADAS_OBJ_PRECEDING

        messages.append(CANMessage(
            msg_id=msg_id,
            timestamp_ms=round(timestamp_ms, 2),
            obj_type=det.obj_class,
            x_position=x_pos,
            y_position=y_pos,
            est_distance_m=est_dist,
            confidence=round(det.confidence, 3),
            segment_target=det.segments_affected[0] if det.segments_affected else -1,
        ))

    return messages


# ============================================================
# DASHCAM METADATA PARSER
# ============================================================

def parse_dashcam_overlay(frame: np.ndarray) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    Try to parse speed/GPS from the REDTIGER dashcam text overlay at bottom of frame.
    Returns (speed_kmh, lat, lon) or None for each if not parseable.
    This is best-effort — OCR is expensive, so we do simple region crop + skip for now.
    The dashcam text format is: REDTIGER F7N 2026/02/06 10:48:06 PM 033KM/H N:13.1077 E:77.5278
    """
    # For now, return None — we can add pytesseract later if needed
    # The important data is in the frame_data.json timestamps
    return None, None, None


# ============================================================
# VIDEO ANNOTATOR (for processed_video.mp4)
# ============================================================

def annotate_frame(frame: np.ndarray, detections: List[Detection],
                   segments: List[BeamSegment], frame_data: FrameData) -> np.ndarray:
    """Draw detection boxes and beam overlay on frame for processed video output."""
    annotated = frame.copy()

    # Draw detection bounding boxes
    for det in detections:
        x1, y1, x2, y2 = det.bbox
        if det.is_hazard:
            color = (0, 0, 255)  # red for hazards
            thickness = 3
        elif det.is_oncoming:
            color = (0, 165, 255)  # orange for oncoming
            thickness = 2
        else:
            color = (255, 200, 0)  # cyan-ish for preceding
            thickness = 2

        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, thickness)

        label = f"{det.obj_class} ({det.estimated_distance})"
        label_size, _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(annotated, (x1, y1 - label_size[1] - 6), (x1 + label_size[0] + 4, y1), color, -1)
        cv2.putText(annotated, label, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    # Draw beam segment overlay — VERY subtle, per-segment alpha
    for seg in segments:
        x1 = seg.segment_id * SEGMENT_WIDTH
        x2 = x1 + SEGMENT_WIDTH
        y1 = ROAD_ZONE_TOP
        y2 = ROAD_ZONE_BOTTOM

        pwm = seg.actual_pwm

        if seg.reason == 'hazard_highlight':
            color = (0, 180, 255)  # amber
            alpha = 0.12
        elif seg.reason == 'dim_oncoming':
            color = (0, 0, 160)  # dark red
            alpha = 0.10 * (1.0 - pwm)  # only visible when actually dimmed
        elif seg.reason == 'dim_preceding':
            color = (160, 80, 0)  # blue
            alpha = 0.06
        else:
            # Full beam: just a thin border, no fill
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 60, 0), 1)
            continue

        # Draw this segment's overlay with its own alpha
        seg_overlay = annotated[y1:y2, x1:x2].copy()
        cv2.rectangle(seg_overlay, (0, 0), (x2 - x1, y2 - y1), color, -1)
        annotated[y1:y2, x1:x2] = cv2.addWeighted(seg_overlay, alpha, annotated[y1:y2, x1:x2], 1.0 - alpha, 0)

    # Draw segment bar at bottom
    bar_y = FRAME_HEIGHT - 38
    bar_h = 18
    for seg in segments:
        x1 = seg.segment_id * SEGMENT_WIDTH + 2
        x2 = x1 + SEGMENT_WIDTH - 4
        pwm = seg.actual_pwm

        # Color based on state
        if seg.reason == 'hazard_highlight':
            bar_color = (0, 200, 255)
        elif pwm < 0.2:
            bar_color = (0, 0, 200)  # red = heavy dim
        elif pwm < 0.5:
            bar_color = (0, 140, 255)  # orange = partial dim
        else:
            g = int(180 * pwm)
            bar_color = (0, g, 0)  # green intensity = PWM level

        filled_h = int(bar_h * pwm)
        cv2.rectangle(annotated, (x1, bar_y + bar_h - filled_h), (x2, bar_y + bar_h), bar_color, -1)
        cv2.rectangle(annotated, (x1, bar_y), (x2, bar_y + bar_h), (80, 80, 80), 1)

    # Draw metrics text overlay (top-left)
    metrics = [
        f"BharatBeam ADB | Seg: {frame_data.segments_dimmed} dimmed / {NUM_SEGMENTS}",
        f"Objects: {frame_data.num_vehicles}V {frame_data.num_hazards}H | "
        f"Glare Red: {frame_data.glare_reduction_pct:.0f}% | "
        f"Road Illum: {frame_data.road_illumination_pct:.0f}%",
        f"Latency: {frame_data.total_latency_ms:.1f}ms | Frame: {frame_data.frame_number}",
    ]

    for i, text in enumerate(metrics):
        y = 25 + i * 22
        cv2.putText(annotated, text, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

    return annotated


# ============================================================
# MAIN PIPELINE
# ============================================================

def process_video(input_path: str, output_dir: str, process_every_n: int = 1):
    """
    Main processing pipeline.

    Args:
        input_path: Path to raw dashcam footage
        output_dir: Directory to write outputs
        process_every_n: Process every Nth frame (1 = all frames, 2 = half, etc.)
                         For YOLO efficiency. Beam states interpolate between.
    """
    os.makedirs(output_dir, exist_ok=True)

    cap = cv2.VideoCapture(input_path)
    if not cap.isOpened():
        raise ValueError(f"Cannot open video: {input_path}")

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print(f"[Pipeline] Input: {input_path}")
    print(f"[Pipeline] Frames: {total_frames}, FPS: {fps}, Resolution: {width}x{height}")
    print(f"[Pipeline] Processing every {process_every_n} frame(s)")
    print(f"[Pipeline] Output dir: {output_dir}")

    # Video writer for annotated output
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out_video_path = os.path.join(output_dir, 'processed_video.mp4')
    writer = cv2.VideoWriter(out_video_path, fourcc, fps, (width, height))

    # Initialize components
    detector = DetectionEngine()
    beam_ctrl = BeamController()

    # Storage for all frame data
    all_frame_data = []
    last_detections = []  # cache detections for skipped frames

    frame_num = 0
    t_start = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        timestamp_s = frame_num / fps
        timestamp_ms = timestamp_s * 1000

        # Run detection (on every Nth frame, reuse last for others)
        if frame_num % process_every_n == 0:
            detections, det_latency = detector.detect(frame)
            last_detections = detections
        else:
            detections = last_detections
            det_latency = 0.0

        # Compute beam state
        segments, beam_latency = beam_ctrl.compute_target(detections)

        # Generate CAN messages
        can_msgs = generate_can_messages(detections, timestamp_ms)

        # Parse dashcam metadata
        speed, lat, lon = parse_dashcam_overlay(frame)

        # Compute aggregate metrics
        num_vehicles = sum(1 for d in detections if d.obj_class in
                          ('car', 'truck', 'bus', 'motorcycle', 'headlight', 'taillight'))
        num_hazards = sum(1 for d in detections if d.is_hazard)
        num_oncoming = sum(1 for d in detections if d.is_oncoming)

        segs_dimmed = sum(1 for s in segments if s.actual_pwm < 0.8)
        segs_full = sum(1 for s in segments if s.actual_pwm >= 0.8)
        segs_highlighted = sum(1 for s in segments if s.reason == 'hazard_highlight')

        # Glare reduction: what % of oncoming light are we blocking
        total_oncoming_segs = sum(len(d.segments_affected) for d in detections if d.is_oncoming)
        dimmed_oncoming_segs = sum(1 for s in segments
                                   if s.actual_pwm < 0.3 and s.reason == 'dim_oncoming')
        glare_reduction = (dimmed_oncoming_segs / max(1, total_oncoming_segs)) * 100

        # Road illumination: what % of segments are at >50% brightness
        road_illumination = (sum(1 for s in segments if s.actual_pwm > 0.5) / NUM_SEGMENTS) * 100

        total_latency = det_latency + beam_latency

        # Build frame data
        fd = FrameData(
            frame_number=frame_num,
            timestamp_s=round(timestamp_s, 4),
            timestamp_ms=round(timestamp_ms, 2),
            speed_kmh=speed,
            gps_lat=lat,
            gps_lon=lon,
            detections=detections,
            num_vehicles=num_vehicles,
            num_hazards=num_hazards,
            num_oncoming=num_oncoming,
            segments=segments,
            segments_dimmed=segs_dimmed,
            segments_full=segs_full,
            segments_highlighted=segs_highlighted,
            glare_reduction_pct=round(glare_reduction, 1),
            road_illumination_pct=round(road_illumination, 1),
            can_messages=can_msgs,
            detection_latency_ms=round(det_latency, 2),
            beam_calc_latency_ms=round(beam_latency, 3),
            total_latency_ms=round(total_latency, 2),
        )

        all_frame_data.append(asdict(fd))

        # Annotate and write video frame
        annotated = annotate_frame(frame, detections, segments, fd)
        writer.write(annotated)

        # Progress logging
        if frame_num % 100 == 0:
            elapsed = time.time() - t_start
            fps_actual = (frame_num + 1) / max(0.001, elapsed)
            pct = (frame_num / total_frames) * 100
            print(f"  [{pct:5.1f}%] Frame {frame_num}/{total_frames} | "
                  f"{fps_actual:.1f} fps | "
                  f"Dets: {len(detections)} | Dimmed: {segs_dimmed}/{NUM_SEGMENTS} | "
                  f"Latency: {total_latency:.1f}ms")

        frame_num += 1

    cap.release()
    writer.release()

    elapsed_total = time.time() - t_start
    print(f"\n[Pipeline] Done! Processed {frame_num} frames in {elapsed_total:.1f}s "
          f"({frame_num / elapsed_total:.1f} fps)")

    # ---- Write JSON outputs ----

    # Full frame data (large file — every frame, every detection)
    full_json_path = os.path.join(output_dir, 'frame_data.json')
    print(f"[Pipeline] Writing full frame data to {full_json_path}...")
    with open(full_json_path, 'w') as f:
        json.dump({
            'metadata': {
                'source_video': os.path.basename(input_path),
                'total_frames': frame_num,
                'fps': fps,
                'width': width,
                'height': height,
                'duration_s': frame_num / fps,
                'num_segments': NUM_SEGMENTS,
                'processed_at': time.strftime('%Y-%m-%d %H:%M:%S'),
                'process_every_n': process_every_n,
            },
            'frames': all_frame_data,
        }, f)
    file_size_mb = os.path.getsize(full_json_path) / (1024 * 1024)
    print(f"[Pipeline] frame_data.json: {file_size_mb:.1f} MB")

    # Lightweight timeline (just segment PWMs per frame — for quick frontend scrubbing)
    timeline_path = os.path.join(output_dir, 'segments_timeline.json')
    print(f"[Pipeline] Writing segments timeline to {timeline_path}...")
    timeline = []
    for fd in all_frame_data:
        timeline.append({
            't': fd['timestamp_s'],
            'pwm': [s['actual_pwm'] for s in fd['segments']],
            'reasons': [s['reason'] for s in fd['segments']],
            'nv': fd['num_vehicles'],
            'nh': fd['num_hazards'],
            'gr': fd['glare_reduction_pct'],
            'ri': fd['road_illumination_pct'],
            'lat': fd['total_latency_ms'],
            'sd': fd['segments_dimmed'],
        })
    with open(timeline_path, 'w') as f:
        json.dump({
            'fps': fps,
            'num_segments': NUM_SEGMENTS,
            'total_frames': frame_num,
            'duration_s': frame_num / fps,
            'timeline': timeline,
        }, f)
    tl_size_mb = os.path.getsize(timeline_path) / (1024 * 1024)
    print(f"[Pipeline] segments_timeline.json: {tl_size_mb:.1f} MB")

    # Summary stats
    print(f"\n[Pipeline] === SUMMARY ===")
    total_dets = sum(len(fd['detections']) for fd in all_frame_data)
    frames_with_oncoming = sum(1 for fd in all_frame_data if fd['num_oncoming'] > 0)
    frames_with_hazards = sum(1 for fd in all_frame_data if fd['num_hazards'] > 0)
    avg_latency = np.mean([fd['total_latency_ms'] for fd in all_frame_data])
    avg_dimmed = np.mean([fd['segments_dimmed'] for fd in all_frame_data])
    avg_glare_red = np.mean([fd['glare_reduction_pct'] for fd in all_frame_data
                             if fd['num_oncoming'] > 0]) if frames_with_oncoming else 0

    print(f"  Total detections: {total_dets}")
    print(f"  Frames with oncoming vehicles: {frames_with_oncoming}/{frame_num} "
          f"({frames_with_oncoming/frame_num*100:.1f}%)")
    print(f"  Frames with hazards: {frames_with_hazards}/{frame_num}")
    print(f"  Avg segments dimmed: {avg_dimmed:.1f}/{NUM_SEGMENTS}")
    print(f"  Avg glare reduction (when oncoming): {avg_glare_red:.1f}%")
    print(f"  Avg processing latency: {avg_latency:.1f}ms")
    print(f"\n  Output video: {out_video_path}")
    print(f"  Frame data: {full_json_path}")
    print(f"  Timeline: {timeline_path}")


# ============================================================
# CLI
# ============================================================

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='BharatBeam Video Processing Pipeline')
    parser.add_argument('--input', '-i', required=True, help='Input video file')
    parser.add_argument('--output', '-o', default='output', help='Output directory')
    parser.add_argument('--every', '-e', type=int, default=2,
                        help='Process every Nth frame for YOLO (1=all, 2=half, etc.)')
    args = parser.parse_args()

    process_video(args.input, args.output, args.every)
