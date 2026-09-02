# BRIEF — "Which file to download"
Write 3 short paragraphs, 165 words maximum.
FACTS:
- Three sizes were measured. The 8-bit file is 9.11 gigabytes, the 4-bit file
  5.38 gigabytes, the 2-bit file 3.60 gigabytes.
- How different each is from the original unshrunk model, measured over 294,912
  words of text: the 8-bit file picks the same next word 97.6 percent of the
  time, the 4-bit file 85.9 percent, the 2-bit file 76.0 percent.
- A common way of ranking these files, called perplexity, put them in the
  opposite order. It ranked the 4-bit file best and the 8-bit file worst.
- That ranking is wrong here and the reason is simple: the 4-bit file scored
  better than the original model it was made from, which is not possible for a
  copy. A shrunk file cannot know more than its source. Perplexity measures how
  confident a model sounds, not how close it stays to the original.
- Practical advice: if the answer matters, use the 8-bit file. If speed matters
  more than exactness, the 4-bit file is a real trade and not a free one.

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
