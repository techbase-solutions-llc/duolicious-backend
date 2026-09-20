"""Face detection for profile photos (plan: a profile photo has to show the member).

Audit 2026-09-20 found members using a hexagon wallpaper, a dog and an AI bear
head as their profile photo. The nudity classifier scored all three correctly as
not lewd, because that is the only question it answers. Nothing in the codebase
looked for a human face.

These tests assert counts, never pixel values. The negative cases matter most:
they are what actually shipped to production.

`detect_faces` reports what it sees and decides nothing. A missed face costs the
operator one click in the moderation queue; it must never be read as a reject.
"""
from __future__ import annotations

import io
import threading
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from antiabuse.facecheck import FaceBox, detect_faces

FIXTURES = Path(__file__).parent / 'fixtures' / 'facecheck'


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Synthetic negatives, generated here so no file needs committing
# ---------------------------------------------------------------------------

def _flat_colour(size=(600, 600), colour=(41, 62, 94)) -> bytes:
    return _png(Image.new('RGB', size, colour))


def _abstract_pattern(size=(800, 800)) -> bytes:
    """A hexagon wallpaper, which is the exact thing member 113 uploaded."""
    image = Image.new('RGB', size, (18, 24, 38))
    draw = ImageDraw.Draw(image)
    radius = 46
    for row in range(-1, size[1] // radius + 2):
        for column in range(-1, size[0] // radius + 2):
            cx = column * radius * 3 + (row % 2) * radius * 1.5
            cy = row * radius
            points = []
            for corner in range(6):
                angle = corner * 60
                points.append((
                    cx + radius * _cos(angle),
                    cy + radius * _sin(angle),
                ))
            draw.polygon(points, outline=(70, 110, 160))
    return _png(image)


def _cos(degrees: float) -> float:
    import math
    return math.cos(math.radians(degrees))


def _sin(degrees: float) -> float:
    import math
    return math.sin(math.radians(degrees))


# ---------------------------------------------------------------------------
# Negatives: the cases that shipped
# ---------------------------------------------------------------------------

def test_a_dog_has_no_face():
    assert len(detect_faces(_read('dog.jpg'))) == 0


def test_a_flat_colour_has_no_face():
    assert len(detect_faces(_flat_colour())) == 0


def test_an_abstract_pattern_has_no_face():
    assert len(detect_faces(_abstract_pattern())) == 0


# ---------------------------------------------------------------------------
# Positives
# ---------------------------------------------------------------------------

def test_a_frontal_portrait_has_exactly_one_face():
    assert len(detect_faces(_read('face-frontal.jpg'))) == 1


def test_a_profile_portrait_still_finds_the_face():
    assert len(detect_faces(_read('face-profile.jpg'))) >= 1


def test_a_two_person_photo_finds_two_faces():
    assert len(detect_faces(_read('faces-two.jpg'))) == 2


def test_a_small_face_in_a_wide_shot_is_still_found():
    """The portrait pasted small into a wide landscape canvas."""
    portrait = Image.open(io.BytesIO(_read('face-frontal.jpg'))).convert('RGB')
    portrait.thumbnail((120, 120), Image.LANCZOS)

    wide = Image.new('RGB', (1600, 600), (196, 205, 214))
    wide.paste(portrait, (1180, 300))

    faces = detect_faces(_png(wide))

    assert len(faces) >= 1
    assert faces[0].area_fraction < 0.02


def test_a_box_from_a_downscaled_image_is_reported_in_the_original_pixels():
    """An image over the working limit is shrunk before detection.

    The box has to come back in the coordinates the caller handed in, not the
    coordinates the detector saw, or a crop built from it lands nowhere near the
    face.
    """
    portrait = Image.open(io.BytesIO(_read('face-frontal.jpg'))).convert('RGB')

    huge = Image.new('RGB', (2400, 2400), (196, 205, 214))
    huge.paste(portrait, (1500, 1500))

    faces = detect_faces(_png(huge))

    assert len(faces) == 1
    box = faces[0]

    # The face sits inside the pasted portrait, which occupies the lower right.
    assert box.x > 1200
    assert box.y > 1200
    assert box.x + box.width <= 2400
    assert box.y + box.height <= 2400


def test_a_face_box_carries_a_confidence_and_an_area_fraction():
    faces = detect_faces(_read('face-frontal.jpg'))

    assert faces
    box = faces[0]
    assert isinstance(box, FaceBox)
    assert 0.0 < box.confidence <= 1.0
    assert 0.0 < box.area_fraction <= 1.0
    assert box.width > 0 and box.height > 0


# ---------------------------------------------------------------------------
# It never raises. Every one of these returns cleanly.
# ---------------------------------------------------------------------------

def _cmyk_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new('CMYK', (400, 400), (10, 20, 30, 40)).save(buffer, format='JPEG')
    return buffer.getvalue()


def _palettised_png() -> bytes:
    return _png(Image.new('RGB', (300, 300), (120, 30, 30)).convert('P'))


def _animated_gif() -> bytes:
    buffer = io.BytesIO()
    frames = [Image.new('P', (200, 200), index) for index in range(1, 4)]
    frames[0].save(buffer, format='GIF', save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def _truncated_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new('RGB', (400, 400), (10, 20, 30)).save(buffer, format='JPEG')
    return buffer.getvalue()[:180]


GARBAGE = {
    'zero bytes': b'',
    'one byte': b'\x00',
    'plain text': b'this is not an image, it is a sentence',
    'random bytes': bytes(range(256)) * 4,
    'jpeg header only': b'\xff\xd8\xff\xe0',
    'truncated jpeg': _truncated_jpeg(),
    'cmyk jpeg': _cmyk_jpeg(),
    'palettised png': _palettised_png(),
    'animated gif': _animated_gif(),
    'enormous blob': b'\xff' * (11 * 1024 * 1024),
}


@pytest.mark.parametrize('label', sorted(GARBAGE))
def test_garbage_returns_an_empty_list_and_never_raises(label):
    result = detect_faces(GARBAGE[label])
    assert result == []


def test_a_non_bytes_argument_returns_an_empty_list():
    assert detect_faces(None) == []
    assert detect_faces('a string, not bytes') == []


def test_a_model_that_will_not_load_returns_an_empty_list(monkeypatch):
    import antiabuse.facecheck as facecheck

    monkeypatch.setattr(facecheck, '_DETECTOR', None)
    monkeypatch.setattr(facecheck, '_DETECTOR_UNAVAILABLE', False)
    monkeypatch.setattr(
        facecheck,
        '_create_detector',
        lambda: (_ for _ in ()).throw(RuntimeError('no model on disk')),
    )

    assert facecheck.detect_faces(_read('face-frontal.jpg')) == []


def test_a_detector_that_raises_mid_inference_returns_an_empty_list(monkeypatch):
    import antiabuse.facecheck as facecheck

    class Exploding:
        def setInputSize(self, size):
            raise RuntimeError('boom')

        def detect(self, frame):
            raise RuntimeError('boom')

    monkeypatch.setattr(facecheck, '_get_detector', lambda: Exploding())

    assert facecheck.detect_faces(_read('face-frontal.jpg')) == []


# ---------------------------------------------------------------------------
# The model loads once per process, and concurrently is still once
# ---------------------------------------------------------------------------

def test_the_model_is_created_once_per_process(monkeypatch):
    import antiabuse.facecheck as facecheck

    real = facecheck._create_detector
    calls = []

    def counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(facecheck, '_DETECTOR', None)
    monkeypatch.setattr(facecheck, '_DETECTOR_UNAVAILABLE', False)
    monkeypatch.setattr(facecheck, '_create_detector', counting)

    facecheck.detect_faces(_read('face-frontal.jpg'))
    facecheck.detect_faces(_read('dog.jpg'))
    facecheck.detect_faces(_read('face-frontal.jpg'))

    assert len(calls) == 1


def test_two_threads_racing_the_first_call_still_create_one_model(monkeypatch):
    import antiabuse.facecheck as facecheck

    real = facecheck._create_detector
    calls = []
    start = threading.Barrier(4, timeout=30)

    def slow_counting():
        calls.append(1)
        return real()

    monkeypatch.setattr(facecheck, '_DETECTOR', None)
    monkeypatch.setattr(facecheck, '_DETECTOR_UNAVAILABLE', False)
    monkeypatch.setattr(facecheck, '_create_detector', slow_counting)

    image = _read('face-frontal.jpg')
    results = []

    def worker():
        start.wait()
        results.append(len(facecheck.detect_faces(image)))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()

    assert len(calls) == 1
    assert results == [1, 1, 1, 1]
