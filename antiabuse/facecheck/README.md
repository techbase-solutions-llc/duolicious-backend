# facecheck

Reports the human faces visible in an image. That is the whole module.

## Why it exists

Every member's primary photo was reviewed by eye on 2026-09-20. Fifty accounts
had photos. Three of them were not a person: an abstract hexagon wallpaper, an
AI generated bear head on a suited body, and a German Shepherd.

The only content check running at the time was the nudity classifier in
`antiabuse/antiporn`, and it was not wrong. It answers one question, "is this
lewd", and it scored the wallpaper at 0.052 and the bear at 0.065, which is
correct. Upload itself checks format, size, dimensions and an exact MD5 against
`banned_photo_hash`. Nothing anywhere asked whether a person was in the frame.

## What it does not do

- **It does not prove the photo is of that member.** That needs a face embedding
  and a reference to compare against, and today there is no reference: the
  verification selfie is hard deleted after three days and only an MD5 survives.
- **It does not decide anything.** No status, no threshold on how big a face has
  to be, no opinion about what should happen next.

## A false reject is worse than a false accept

An empty result means "I did not see a face". It does not mean "there is no
person here", and it must never be wired to an automatic takedown. Wrongly
hiding a real member's photo tells a real person that they look fake.

Members whose faces are small, in heavy shadow, partly masked, turned away or
shot from behind are still members. The detector is good, not perfect. The
caller's job is to put an empty result in front of a human.

## Using it

```python
from antiabuse.facecheck import detect_faces

faces = detect_faces(image_bytes)
if not faces:
    ...  # ask a person. never reject.
```

`detect_faces(image_bytes: bytes) -> list[FaceBox]`, sorted largest first. Each
`FaceBox` carries `x`, `y`, `width` and `height` in the coordinates of the image
that was passed in, YuNet's own `confidence`, and `area_fraction`, the box area
over the whole frame area.

The function is pure over its argument. No network, no database, no state except
the detector, which is built once per process.

## It never raises

Every bad input returns `[]` and logs: zero bytes, a truncated or corrupt file,
plain text, something that is not an image at all, CMYK, palettised, animated,
an image larger than `constants.MAX_IMAGE_BYTES`, one with more than 50 million
pixels, and a model file that will not load. This follows how
`antiabuse.bannedphoto.is_banned_photo` and `duotypes.Base64File` already behave:
a bad photo is never allowed to take the pipeline down with it.

A model that fails to load is remembered, not retried per image, so a missing
weights file produces one log line rather than one per photo.

## The model

`face_detection_yunet_2023mar.onnx`, 232 KB, is committed beside this file, the
same way `antiabuse/antiporn` commits its own 210 MB weights. Nothing is fetched
at runtime, so the cron container is self-contained and a network outage cannot
quietly disable the check.

- Upstream: [opencv_zoo, face_detection_yunet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
- File: `face_detection_yunet_2023mar.onnx`, sha256
  `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`
- Runtime: `cv2.FaceDetectorYN` from `opencv-python-headless`, pinned in
  `requirements.txt`. No new inference runtime is introduced.

`.gitattributes` carries a rule keeping this path out of git LFS. The default
`*.onnx` rule would store it as a pointer, and the droplet deploy is a plain
`git reset --hard`, so a pointer would land on production instead of a model.
The failure would be quiet: the module logs once and reports no faces, which
looks the same as a member with no face in frame. antiporn sidesteps the same
rule by accident, because its parts are named `.part00` rather than `.onnx`.

Licence, from `opencv_zoo/models/face_detection_yunet/LICENSE`:

```
MIT License

Copyright (c) 2020 Shiqi Yu <shiqi.yu@gmail.com>

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Threshold

One number, `_SCORE_THRESHOLD`, and it is YuNet's own confidence cut rather than
a policy of ours. It sits at 0.6, below the OpenCV default of 0.9, because
recall is the direction that protects members: a face the detector sees is a
photo nobody has to review by hand, and a face it misses only costs the operator
a click.

## Threading

The detector is built once per process, under a lock, so cron threads racing the
first photo do not each pay for a load. `setInputSize` mutates the detector, so
the same lock covers inference. Detection on a 450px render is about a
millisecond, so serialising it costs nothing worth measuring.

## Tests

`tests/test_face_check.py`. Fixtures and their provenance are in
`tests/fixtures/facecheck/README.md`. No member photo is committed to the repo.
