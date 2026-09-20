"""Does this photo contain a human face?

Audit 2026-09-20 found members presenting themselves with a hexagon wallpaper, a
photo of a dog and an AI generated bear head. The only content check that ran was
the nudity classifier in `antiabuse/antiporn`, and it answered its own question
correctly every time: none of those images is lewd. Nothing looked for a person.

This module answers the missing question and nothing else. It reports the faces
it can see, with a confidence and how much of the frame each one fills. It does
not decide, it does not threshold on area, and it does not know what a caller
intends to do with the answer.

**A false reject is worse than a false accept.** A member whose face is small, in
shadow, masked or turned away is still a member. An empty list from this function
means "I did not see a face", never "there is no person here", and it must never
be wired to an automatic takedown. The plan this module belongs to routes an
empty result to `manual_review` so a human decides.

Conventions follow `antiabuse/antiporn`: the model weights are committed
alongside the code rather than fetched at runtime, so the cron container is
self-contained and an outage cannot silently disable the check. YuNet is 232 KB
next to antiporn's 210 MB, so it costs the image almost nothing.

Degradation follows `antiabuse.bannedphoto.is_banned_photo` and
`duotypes.Base64File`: bad input never propagates out of the photo pipeline. Here
that means `detect_faces` returns `[]` and logs, for every kind of bad input
there is, including a model that will not load.

Public surface:
  FaceBox               dataclass: x, y, width, height, confidence, area_fraction
  detect_faces(bytes)   the whole module
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

import numpy as np
from PIL import Image

import constants

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
#
# YuNet, from the OpenCV model zoo, shipped as a committed ONNX file exactly as
# antiporn ships its own weights. Small enough that it needs no splitting into
# 50 MB parts. Provenance and licence are in the README beside it.

_MODEL_PATH = Path(__file__).parent / 'face_detection_yunet_2023mar.onnx'

# YuNet's own confidence cut. This is the only threshold in the module and it is
# the detector's, not a policy of ours. It sits below the OpenCV default of 0.9
# because recall is the direction that protects members: a face this module sees
# is a photo nobody has to look at by hand, and a face it misses only costs the
# operator a click. It is never a reason to take a photo down.
_SCORE_THRESHOLD = 0.6

# Non maximum suppression and the cap on candidates, both OpenCV defaults.
_NMS_THRESHOLD = 0.3
_TOP_K = 5000

# Big images are slow and add nothing: the photo pipeline feeds this a 450px
# render. Downscale anything larger, never upscale, and report boxes back in the
# coordinates of the image that was handed in.
_MAX_WORKING_DIM = 1600

# A frame with more pixels than this is not a profile photo, it is a problem.
# Pillow raises its own decompression bomb warning around 89 megapixels; this is
# an explicit floor under that so the cron cannot be stalled by one upload.
_MAX_PIXELS = 50_000_000

_LOCK = threading.Lock()
_DETECTOR = None
_DETECTOR_UNAVAILABLE = False


@dataclass(frozen=True)
class FaceBox:
    """One detected face, in the coordinates of the image that was passed in.

    `confidence` is YuNet's own score for the box. `area_fraction` is the box
    area divided by the whole image area, so a head and shoulders portrait lands
    near 0.1 and a face across a crowd lands near 0.001. Neither field carries a
    verdict; they exist so a human queue can be sorted sensibly.
    """
    x: int
    y: int
    width: int
    height: int
    confidence: float
    area_fraction: float


def _create_detector():
    """Build the YuNet detector. Separate so tests can count the calls."""
    import cv2

    return cv2.FaceDetectorYN.create(
        model=str(_MODEL_PATH),
        config='',
        input_size=(320, 320),
        score_threshold=_SCORE_THRESHOLD,
        nms_threshold=_NMS_THRESHOLD,
        top_k=_TOP_K,
    )


def _get_detector():
    """The process wide detector, or None if it could not be built.

    Built once, under a lock, so two cron threads racing the first photo of the
    process do not each pay for a load. A failure is remembered rather than
    retried per image: if the weights are missing, they will still be missing on
    the next photo, and a retry loop would turn one problem into a log flood.
    """
    global _DETECTOR, _DETECTOR_UNAVAILABLE

    if _DETECTOR is not None or _DETECTOR_UNAVAILABLE:
        return _DETECTOR

    with _LOCK:
        if _DETECTOR is not None or _DETECTOR_UNAVAILABLE:
            return _DETECTOR
        try:
            _DETECTOR = _create_detector()
        except Exception:
            _DETECTOR_UNAVAILABLE = True
            logger.exception(
                'face check disabled: the YuNet detector would not load from %s',
                _MODEL_PATH,
            )
        return _DETECTOR


# ---------------------------------------------------------------------------
# Decoding
# ---------------------------------------------------------------------------

def _decode(image_bytes: bytes):
    """Bytes to a (BGR numpy frame, original size) pair, or None.

    None means the bytes are not a usable image.

    Pillow rather than cv2.imdecode, matching antiporn, because it is the
    decoder the rest of the photo pipeline already trusts and it handles CMYK,
    palettised, animated and HEIF inputs without special cases. Every failure is
    a None, never an exception.
    """
    if not isinstance(image_bytes, (bytes, bytearray, memoryview)):
        logger.warning(
            'face check skipped: expected bytes, got %s', type(image_bytes).__name__)
        return None

    if not image_bytes:
        logger.warning('face check skipped: zero bytes')
        return None

    if len(image_bytes) > constants.MAX_IMAGE_BYTES:
        logger.warning(
            'face check skipped: %d bytes is over the %d byte limit',
            len(image_bytes), constants.MAX_IMAGE_BYTES)
        return None

    try:
        image = Image.open(BytesIO(image_bytes))
    except Exception:
        logger.warning('face check skipped: bytes are not an image', exc_info=True)
        return None

    try:
        width, height = image.size
        if width < 1 or height < 1:
            logger.warning('face check skipped: image has no area')
            return None
        if width * height > _MAX_PIXELS:
            logger.warning(
                'face check skipped: %dx%d is over the %d pixel limit',
                width, height, _MAX_PIXELS)
            return None

        # Animated inputs are checked on their first frame. Converting to RGB
        # also flattens CMYK, palettised, greyscale and transparency cases.
        image = image.convert('RGB')

        longest = max(image.size)
        if longest > _MAX_WORKING_DIM:
            scale = _MAX_WORKING_DIM / longest
            image = image.resize(
                (max(1, int(width * scale)), max(1, int(height * scale))),
                Image.BILINEAR,
            )

        # YuNet wants BGR, which is RGB reversed on the channel axis.
        frame = np.asarray(image, dtype=np.uint8)[:, :, ::-1]
        return np.ascontiguousarray(frame), (width, height)
    except Exception:
        logger.warning('face check skipped: image would not decode', exc_info=True)
        return None
    finally:
        try:
            image.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# The whole module
# ---------------------------------------------------------------------------

def detect_faces(image_bytes: bytes) -> list[FaceBox]:
    """Report the human faces visible in one image.

    Pure over its argument: no network, no database, no state beyond the lazily
    built detector. Never raises, for any input at all. An empty list means the
    detector saw nothing, which is a reason to ask a person, never a reason to
    take a photo down.
    """
    try:
        decoded = _decode(image_bytes)
        if decoded is None:
            return []
        frame, (original_width, original_height) = decoded

        detector = _get_detector()
        if detector is None:
            return []

        height, width = frame.shape[:2]
        area = float(width * height)

        # setInputSize mutates the detector, so the lock covers inference too.
        # One detector shared across cron threads is cheap; a torn input size is
        # not. Detection on a 450px render is around a millisecond.
        with _LOCK:
            detector.setInputSize((width, height))
            _, raw = detector.detect(frame)

        if raw is None:
            return []

        scale_x = original_width / float(width)
        scale_y = original_height / float(height)

        faces = []
        for row in raw:
            box_x, box_y, box_w, box_h = (float(value) for value in row[:4])
            confidence = float(row[-1])
            if box_w <= 0 or box_h <= 0:
                continue
            faces.append(FaceBox(
                x=int(round(box_x * scale_x)),
                y=int(round(box_y * scale_y)),
                width=int(round(box_w * scale_x)),
                height=int(round(box_h * scale_y)),
                confidence=confidence,
                area_fraction=(box_w * box_h) / area,
            ))

        faces.sort(key=lambda face: face.area_fraction, reverse=True)
        return faces
    except Exception:
        logger.exception('face check failed, reporting no faces')
        return []
