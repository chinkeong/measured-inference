# BRIEF — "Images"
Write 3 short paragraphs, 170 words maximum.
FACTS:
- The model does not pretend to see. Sent a question about an image with no
  image attached, it answered: it did not see any image and asked for one.
  Asked whether a red triangle was in a picture that contained a black circle,
  it said no and named the circle.
- But it misreads small text confidently. A six-digit number was drawn into a
  test image at several sizes. At 1,536 by 864 pixels and below it got the
  number wrong every time, in three tries at each size. At 1,600 by 900 pixels
  and above it got it right every time.
- When it was wrong it never said so. It returned a confident six-digit answer,
  and the same wrong answer on all three tries, so running it twice gives
  agreement that looks like confirmation.
- Practical advice: send screenshots at 1,600 by 900 pixels or wider.
- Cost: about 1,010 pixels per token up to about 2 million pixels. Above that
  the image is shrunk, so a 4K screenshot costs the same as a 2K one and
  carries half the detail per token.

RULES THAT BIND YOU
- You have NO file access and need none. Do not attempt to write or save any
  file. Do not mention files, permissions or saving. Print the prose only.
- Invent nothing. Every number you may use is listed below. If a claim needs a
  figure that is not here, leave the claim out.
- This is a WRITING pass, not a fact pass. Do not change a number, unit or
  condition.
- Plain international English. Short sentences. Common vocabulary. No metaphor,
  no idiom, no wordplay. Written for two readers at once: a non-expert setting
  up a machine at home or in a small lab, and a reader whose first language is
  not English.
- Banned: "sweet spot", "free lunch", "rule of thumb", "under the hood",
  "game changer", "punches above its weight".
- Every number carries its unit and its plain meaning in the same sentence.
- Do NOT open with a caveat, a table or a command. Open with the point.
- Do NOT hedge with "it is worth noting", "interestingly", "notably".
- No headings, no bullets, no markup, no horizontal rules. Prose only.
- Do NOT touch the GPU.
OUTPUT: the paragraphs and nothing else. No preamble, no sign-off.
