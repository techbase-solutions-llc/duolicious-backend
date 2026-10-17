-- 0067_quick_questions.sql
-- Quick questions, release 1 (TEC-1845,
-- docs/superpowers/specs/2026-10-13-profile-prompts-design.md, revision of
-- 16 Oct; plan docs/superpowers/plans/2026-10-16-quick-questions-release-1.md).
--
--   prompt_bank        gains format and options. The 14 choice questions from
--                      the guide are seeded active; its 20 open questions are
--                      seeded inactive and wait for written answers in
--                      release 2. Seeded with ON CONFLICT DO NOTHING, so a
--                      second run never undoes the owner's edits.
--   prompt_answer      one answer per member per question. Release 1 fills
--                      choice_key only; text and text_status are release 2's.
--   question_drop      the approved weekly schedule: which question goes live
--                      on which drop day (service/questions/schedule.py).
--   match_question     the one question both members of a match answer.
--   push_subscription.tz             the device's IANA time zone, for 18:00
--                                    local pushes and quiet hours.
--   notification_preference.push_questions (default on, owner decision of
--                      16 Oct) and push_questions_off_at, stamped when a
--                      member turns it off, so switch-offs can be counted.
--   push_tap           a landing from a question push (?src=).
--   person.question_catchup_declined_at  "Not now" on the catch-up offer,
--                      held on every device.
--
-- No question about plural marriage. Idempotent: the deploy may run this
-- file more than once.

ALTER TABLE prompt_bank ADD COLUMN IF NOT EXISTS format TEXT NOT NULL DEFAULT 'text';
ALTER TABLE prompt_bank ADD COLUMN IF NOT EXISTS options JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE prompt_bank DROP CONSTRAINT IF EXISTS prompt_bank_format_check;
-- CASE, not OR: jsonb_array_length raises on a non-array, and only CASE
-- fixes the order of evaluation.
ALTER TABLE prompt_bank ADD CONSTRAINT prompt_bank_format_check CHECK (
  CASE format
    WHEN 'text' THEN options = '[]'::jsonb
    WHEN 'either_or' THEN CASE WHEN jsonb_typeof(options) = 'array'
                               THEN jsonb_array_length(options) = 2 ELSE FALSE END
    WHEN 'pick_one' THEN CASE WHEN jsonb_typeof(options) = 'array'
                              THEN jsonb_array_length(options) BETWEEN 3 AND 4 ELSE FALSE END
    ELSE FALSE
  END);

INSERT INTO prompt_bank (key, text, category, format, options, active, sort) VALUES
  ('host-or-dessert', 'Would you rather host the feast meal or be the guest who brings dessert?',
   'Would you rather', 'either_or',
   '[{"key":"host","label":"Hosting the feast meal"},{"key":"dessert","label":"Bringing dessert"}]', TRUE, 10),
  ('mountains-or-sea', 'Would you rather wake up to mountains or the sea?',
   'Would you rather', 'either_or',
   '[{"key":"mountains","label":"Mountains"},{"key":"sea","label":"The sea"}]', TRUE, 20),
  ('cabin-or-city', 'Would you rather spend a week in a cabin with no signal or a week exploring a city you have never seen?',
   'Would you rather', 'either_or',
   '[{"key":"cabin","label":"A cabin with no signal"},{"key":"city","label":"A new city to explore"}]', TRUE, 30),
  ('grow-or-market', 'Would you rather grow your own vegetables or know every good market stall for miles around?',
   'Would you rather', 'either_or',
   '[{"key":"grow","label":"Growing vegetables"},{"key":"market","label":"Knowing every good market stall"}]', TRUE, 40),
  ('language-or-instrument', 'Would you rather learn a new language or a new instrument?',
   'Would you rather', 'either_or',
   '[{"key":"language","label":"A new language"},{"key":"instrument","label":"A new instrument"}]', TRUE, 50),
  ('coffee-or-tea', 'Coffee, tea or something else?',
   'Mornings, evenings and how you rest', 'pick_one',
   '[{"key":"coffee","label":"Coffee"},{"key":"tea","label":"Tea"},{"key":"other","label":"Something else"}]', TRUE, 60),
  ('morning-or-night', 'Are you up with the sun, or do you do your best thinking after dark?',
   'Mornings, evenings and how you rest', 'either_or',
   '[{"key":"early","label":"Early mornings"},{"key":"late","label":"Late evenings"}]', TRUE, 70),
  ('sabbath-afternoon', 'What does the best Sabbath afternoon look like to you?',
   'Mornings, evenings and how you rest', 'pick_one',
   '[{"key":"walk","label":"A long walk"},{"key":"nap","label":"A nap"},{"key":"table","label":"A table full of friends"}]', TRUE, 80),
  ('people-or-quiet', 'When you need to recharge, do you look for people or for quiet?',
   'Mornings, evenings and how you rest', 'either_or',
   '[{"key":"people","label":"People"},{"key":"quiet","label":"Quiet"}]', TRUE, 90),
  ('family-table', 'Big family table or small and cosy?',
   'Family life and traditions', 'either_or',
   '[{"key":"big","label":"A big family table"},{"key":"cosy","label":"Small and cosy"}]', TRUE, 100),
  ('window-or-aisle', 'Window seat or aisle?',
   'Little preferences that reveal a lot', 'either_or',
   '[{"key":"window","label":"The window seat"},{"key":"aisle","label":"The aisle seat"}]', TRUE, 110),
  ('early-or-late', 'Are you early, on time or a little late?',
   'Little preferences that reveal a lot', 'pick_one',
   '[{"key":"early","label":"Early"},{"key":"on-time","label":"On time"},{"key":"late","label":"A little late"}]', TRUE, 120),
  ('plan-or-decide', 'Do you plan a trip down to the hour or decide when you get there?',
   'Little preferences that reveal a lot', 'either_or',
   '[{"key":"plan","label":"Planning to the hour"},{"key":"decide","label":"Deciding on the day"}]', TRUE, 130),
  ('city-town-or-country', 'City, small town or a long drive to the nearest neighbour?',
   'Little preferences that reveal a lot', 'pick_one',
   '[{"key":"city","label":"The city"},{"key":"town","label":"A small town"},{"key":"drive","label":"A long drive to the nearest neighbour"}]', TRUE, 140),
  ('cook-for-guests', 'What dish could you cook for guests without looking at a recipe?', 'Favourites', 'text', '[]', FALSE, 200),
  ('feast-food', 'Which feast food do you look forward to all year?', 'Favourites', 'text', '[]', FALSE, 210),
  ('song-every-word', 'What song have you played so many times you know every word?', 'Favourites', 'text', '[]', FALSE, 220),
  ('book-or-album', 'Which book or album would you hand to a friend who wanted to understand you?', 'Favourites', 'text', '[]', FALSE, 230),
  ('hobby-to-start', 'What hobby have you always meant to start?', 'Favourites', 'text', '[]', FALSE, 240),
  ('surprisingly-good-at', 'What are you surprisingly good at?', 'Favourites', 'text', '[]', FALSE, 250),
  ('place-to-return', 'Which place have you visited that you would happily go back to tomorrow?', 'Favourites', 'text', '[]', FALSE, 260),
  ('first-hour', 'What does the first hour of your day look like?', 'Mornings, evenings and how you rest', 'text', '[]', FALSE, 270),
  ('ideal-free-day', 'Describe your ideal free day from the moment you wake up.', 'Describe your ideal', 'text', '[]', FALSE, 280),
  ('ideal-kitchen-table', 'Describe your ideal kitchen table: how big, how many chairs and what usually ends up on it.', 'Describe your ideal', 'text', '[]', FALSE, 290),
  ('ideal-trip', 'Describe your ideal trip, including how you would get there.', 'Describe your ideal', 'text', '[]', FALSE, 300),
  ('ideal-picnic', 'Describe your ideal picnic, right down to what is in the basket.', 'Describe your ideal', 'text', '[]', FALSE, 310),
  ('tradition-to-carry-on', 'What family tradition would you love to carry on?', 'Family life and traditions', 'text', '[]', FALSE, 320),
  ('best-cook', 'Who is the best cook in your family, and what do they make?', 'Family life and traditions', 'text', '[]', FALSE, 330),
  ('favourite-feast-gathering', 'What feast gathering has been your favourite so far, and what made it so good?', 'Family life and traditions', 'text', '[]', FALSE, 340),
  ('family-game', 'Which game always comes out when your family gets together?', 'Family life and traditions', 'text', '[]', FALSE, 350),
  ('pet', 'Do you have a pet, or one you dream of having?', 'Family life and traditions', 'text', '[]', FALSE, 360),
  ('secret-chore', 'Which chore do you secretly enjoy?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 370),
  ('thing-with-a-story', 'What is one thing in your home with a story behind it?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 380),
  ('small-good-thing', 'What small thing always makes your day better?', 'Little preferences that reveal a lot', 'text', '[]', FALSE, 390)
ON CONFLICT (key) DO NOTHING;

CREATE TABLE IF NOT EXISTS prompt_answer (
  person_id    INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  prompt_key   TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE ON DELETE CASCADE,
  choice_key   TEXT,
  text         TEXT,
  text_status  TEXT         CHECK (text_status IN ('pending', 'approved', 'rejected')),
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  PRIMARY KEY (person_id, prompt_key),
  CHECK (choice_key IS NOT NULL OR text IS NOT NULL),
  CHECK ((text IS NULL) = (text_status IS NULL))
);
CREATE INDEX IF NOT EXISTS idx__prompt_answer__prompt_choice ON prompt_answer (prompt_key, choice_key);

CREATE TABLE IF NOT EXISTS question_drop (
  live_on      DATE         PRIMARY KEY,
  prompt_key   TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE,
  approved_at  TIMESTAMPTZ,
  created_at   TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS match_question (
  match_id    UUID         PRIMARY KEY REFERENCES ahavah_match(match_id) ON DELETE CASCADE,
  prompt_key  TEXT         NOT NULL REFERENCES prompt_bank(key) ON UPDATE CASCADE ON DELETE CASCADE,
  offered_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

ALTER TABLE push_subscription ADD COLUMN IF NOT EXISTS tz TEXT;

ALTER TABLE notification_preference
  ADD COLUMN IF NOT EXISTS push_questions BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS push_questions_off_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS push_tap (
  id         BIGSERIAL    PRIMARY KEY,
  person_id  INT          NOT NULL REFERENCES person(id) ON DELETE CASCADE,
  src        TEXT         NOT NULL CHECK (src IN ('qpush', 'mpush', 'lpush')),
  tapped_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx__push_tap__tapped_at ON push_tap (tapped_at);
CREATE INDEX IF NOT EXISTS idx__push_tap__person_src ON push_tap (person_id, src, tapped_at);

ALTER TABLE person ADD COLUMN IF NOT EXISTS question_catchup_declined_at TIMESTAMPTZ;
