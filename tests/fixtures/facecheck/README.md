# Face check fixtures

Images `tests/test_face_check.py` runs the detector against.

**No member photo is ever committed here.** The audit of 2026-09-20 is the reason
this check exists, but the photos it looked at belong to the members who uploaded
them. Everything in this folder is either generated at test time or a public
domain image from Wikimedia Commons.

Tests assert counts, never pixel values, so these files can be swapped for
better ones without rewriting the assertions.

## Generated in the test, not committed

| Case | Where |
|---|---|
| Flat colour | `_flat_colour()` in `tests/test_face_check.py`, a plain fill from Pillow |
| Abstract pattern | `_abstract_pattern()`, a hexagon wallpaper, which is what member 113 actually uploaded |
| Small face in a wide shot | `test_a_small_face_in_a_wide_shot_is_still_found`, which pastes `face-frontal.jpg` at 120px into a 1600x600 canvas |
| Corrupt, truncated, CMYK, palettised, animated, enormous, non image | the `GARBAGE` table in the same file |

## Committed, all public domain

Each file was downloaded from Wikimedia Commons and downscaled to 600px on its
long side so the repo stays small and the input resembles the 450px render the
cron actually scores. No other edit was made.

### `face-frontal.jpg`

One clear frontal face.

- Source: [Official portrait of NASA astronaut Jonny Kim](https://commons.wikimedia.org/wiki/File:Jsc2024e052605_alt_(Aug._6,_2024)_---_Official_portrait_of_NASA_astronaut_Jonny_Kim.jpg)
- Author: NASA Johnson Space Center / Josh Valcarcel, 6 August 2024, photo id `jsc2024e052605_alt`
- Licence: public domain, a work of the United States federal government

### `face-profile.jpg`

A face in full right profile, which is the case the detector finds hardest and
the case a member with a side on photo would hit.

- Source: [Calvin Coolidge, head-and-shoulders portrait, right profile](https://commons.wikimedia.org/wiki/File:Calvin_Coolidge,_head-and-shoulders_portrait,_right_profile_LCCN2005676159.jpg)
- Author: John H. Garo, circa 25 October 1923, Library of Congress digital id `cph.3f06438`
- Licence: public domain

### `faces-two.jpg`

Two faces in one frame.

- Source: [Daguerreotype portrait of two young men, circa 1850](https://commons.wikimedia.org/wiki/File:Daguerreotype_portrait_of_two_young_men,_circa_1850.jpg)
- Author: unknown photographer, circa 1850, Metropolitan Museum of Art object 190038101
- Licence: public domain, by age

### `dog.jpg`

A German Shepherd, the same thing member 49 used as a profile photo. The most
important negative in the set, because it is what shipped.

- Source: [GSD Portrait](https://commons.wikimedia.org/wiki/File:GSD_Portrait.jpg)
- Author: Commons user Dogperson3d, own work, 29 August 2007, released into the public domain
- Licence: public domain
