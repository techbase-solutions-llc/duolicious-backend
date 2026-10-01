from antiabuse.antiporn import predict_nsfw
from antiabuse.facecheck import count_faces as count_faces_in
from database.asyncdatabase import api_tx
from service.cron.nsfwphotorunner.sql import *
from service.cron.cronutil import (
    MAX_RANDOM_START_DELAY,
    download_450_images,
    env_int,
    print_stacktrace,
)
import asyncio
import random

NSFW_PHOTO_RUNNER_POLL_SECONDS = env_int('DUO_CRON_NSFW_PHOTO_RUNNER_POLL_SECONDS', 1) # 1 second

print(f'Hello from cron module: {__name__}')

def count_faces(image_data_seq) -> list:
    """How many faces each image shows, or None where the check could not
    look. None matters: an unreadable download or a detector that will not
    load must never be stored as 0, because 0 on a main photo sends it to a
    person. The helper is written never to raise, but this is the photo
    pipeline: if it ever does, the nudity score still has to be written, so
    a failure here costs that one photo its face check and nothing else."""
    counts = []
    for image_data in image_data_seq:
        try:
            counts.append(count_faces_in(image_data))
        except Exception:
            counts.append(None)
    return counts


async def predict_nsfw_photos_once():
    async with api_tx() as tx:
        cur = await tx.execute(Q_50_UNCHECKED_PHOTOS)
        rows = await cur.fetchall()

    uuids = [r['uuid'] for r in rows]

    image_data_seq = await download_450_images(uuids)

    missing_uuids, missing_image_data_seq = [], []
    present_uuids, present_image_data_seq = [], []

    for uuid, image_data in zip(uuids, image_data_seq):
        if image_data:
            present_uuids.append(uuid)
            present_image_data_seq.append(image_data)
        else:
            missing_uuids.append(uuid)
            missing_image_data_seq.append(image_data)

    missing_nsfw_scores = [
        -1.0 for _ in missing_image_data_seq]
    present_nsfw_scores = await asyncio.to_thread(
        predict_nsfw, present_image_data_seq)

    present_face_counts = await asyncio.to_thread(
        count_faces, present_image_data_seq)
    face_counts_ = (
        [None for _ in missing_uuids] + present_face_counts)

    uuids_ = (
        missing_uuids + present_uuids)
    nsfw_scores_ = (
        missing_nsfw_scores + present_nsfw_scores)

    params_seq = [
        dict(uuid=uuid, nsfw_score=nsfw_score, face_count=face_count)
        for uuid, nsfw_score, face_count in zip(uuids_, nsfw_scores_, face_counts_)
    ]

    async with api_tx() as tx:
        await tx.executemany(Q_SET_NSFW_SCORE, params_seq)

async def predict_nsfw_photos_forever():
    await asyncio.sleep(random.randint(0, MAX_RANDOM_START_DELAY))
    while True:
        await print_stacktrace(predict_nsfw_photos_once)
        await asyncio.sleep(NSFW_PHOTO_RUNNER_POLL_SECONDS)
