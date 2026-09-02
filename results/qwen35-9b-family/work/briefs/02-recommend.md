# BRIEF — section 2 "The recommendation"
Write 3 short paragraphs, 150 words total maximum. This is the most important
section on the page: a reader who reads only this must be able to act.
FACTS:
- Recommendation: use Ornith-1.5-9B for work you want finished; use Qwen3.5-9B
  if you need image or video input, because Ornith was measured only for text
  here.
- Both models produce text at the same speed: 84.17 and 83.80 tokens per second
  respectively, a difference of 0.5 percent, which is too small to notice.
- On the same 175 test questions Ornith finished in 4,231 seconds and
  Qwen3.5-9B took 10,235 seconds. Ornith took 41 percent of the time.
- The reason is not speed. It is that Qwen3.5-9B often does not stop. It ran
  past the answer limit on 23 of the 175 questions; Ornith did so on 9.
- An answer that runs past the limit is cut off and scores zero, so the extra
  time produces nothing.
- On the shared test set Ornith scored 68.9 out of 100 and Qwen3.5-9B 61.6.
- Caution the reader: that 7.3 point difference is a lean, not a verdict. Each
  individual test used only 25 questions, which is too few to settle small
  differences. The stopping behaviour is the large and consistent finding.

RULES THAT BIND YOU
- Invent nothing. Every number you may use is listed below. If a claim needs a
  figure that is not here, leave the claim out.
- This is a WRITING pass, not a fact pass. Do not change a single number, unit
  or condition.
- Plain international English. Short sentences. Common vocabulary. No metaphor,
  no idiom, no wordplay, no cultural reference. Written for two readers at
  once: a non-expert setting up a machine at home or in a small lab, and a
  reader whose first language is not English.
- Banned outright: "sweet spot", "free lunch", "rule of thumb", "punches above
  its weight", "dark horse", "under the hood", "game changer", ""at the end of
  the day". Write what you mean instead.
- Every number carries its unit and its plain meaning in the same sentence.
- Do NOT open with a caveat, a table, or a command. Open with the point.
- Do NOT hedge with "it is worth noting", "interestingly", "it should be said".
- No headings, no bullet lists, no markup of any kind. Prose paragraphs only.
- Do NOT touch the GPU. Do not run anything. You are writing text.
PRINT ONLY THE PARAGRAPHS. No preamble, no sign-off, no commentary.
