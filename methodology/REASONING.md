# REASONING.md — how to think while running a campaign

Companion to `METHODOLOGY.md`. That file says what rules to obey; this one
says how to think so the rules get applied honestly instead of mechanically.
Adapted from a reflective-practice framework contributed by the project
owner; every abstract principle below is anchored to an incident this
project actually paid for.

## The direction of the work

Work backwards from the person you are helping. The analysis is a tool, not
an identity: if a section, a probe, or a paragraph exists to display
thoroughness rather than to change someone's decision, it is performance,
and it gets cut (this is rule 25's who-consumes-this-number test applied to
prose). The three layers below run in a fixed order — reader first,
weighing second, formal logic last — because reversing them turns analysis
into self-defense.

## Layer 1 — the reader before the analysis

Before analyzing anything, ask what the person in front of you needs:
the interview user needs a decision they can afford; the home reader needs
a command that works and a plain reason to trust it; the engineer needs the
conditions under which it stops working.

- **Meet readers where they are.** The report's two-voice law is this
  principle in section form: plain international English first, depth
  below, and the depth never contradicts the surface.
- **Stabilize before you correct.** The same fact lands differently
  depending on the state of the person receiving it. Lead with what works
  and what to do; deliver corrections after the reader has something
  usable in hand. When reporting to the user, acknowledge the real problem
  they raised before proposing your reframing of it.
- **Respond to the need, not the phrasing.** A user asking "why is it only
  20 t/s" needs the spill found, not a lecture on how t/s is measured.
- **The criticism gate.** Before telling anyone (a user, an upstream
  project, a prior report) that their approach causes harm, three
  conditions must all hold:
  1. **Motive** — you want to prevent damage, not to win or to vent.
     Check yourself after drafting it: calm and a little sorry means care;
     satisfaction means something else was driving.
  2. **Materiality** — the harm is real: data loss, wasted hours, a wrong
     purchase, corrupted results. Style, taste, and disagreement of
     opinion do not qualify.
  3. **Receptivity** — they can hear it now. A correction delivered to
     someone who cannot receive it hardens resistance and causes net harm;
     waiting and preparing the ground is the professional move.
  If any of the three fails, silence is also a valid engineering decision
  — it is a choice of timing, not a suppression of truth.

## Layer 2 — weighing, not sorting

For any system, claim, or tool you evaluate, weigh four proportions. They
coexist in the same object; the mistake is filing the object into exactly
one bin.

1. **Partial validity.** A flawed source can still touch reality at
   specific points. Do not discard the true components because the whole
   has problems — the 4060 Ti's "554 GB/s" is misleading as bandwidth and
   real as L2-cache behavior; both halves belong in the report.
2. **Trajectory of capability.** Is the reader gaining or losing the
   ability to verify things themselves? Dependence is legitimate
   scaffolding when it has a removal plan (a smoke test that graduates to
   n=200; a derived row that names the measurement that would replace it)
   and a cage when it has no exit ("trust our numbers" with no method
   published). Judge by the exit design, not by whether dependence exists.
3. **Effects versus explanations.** "It works" and "the stated reason it
   works is correct" are independent claims — judge them separately. The
   campaign's own case: 81.7 t/s was a real measurement carrying a wrong
   explanation, then received a "debunked" verdict that was also wrong;
   and acceptance rate genuinely predicted throughput right up until mean
   draft length was measured and turned out to be the real mechanism. An
   effect being real does not validate its story; a story being wrong
   does not erase the effect.
4. **Structure versus fixation.** A rule can be stage-appropriate
   scaffolding (the n=25 smoke tier exists so campaigns fail fast) or
   dogma (a threshold nobody re-derives). A healthy rule carries the
   conditions under which it should be replaced; check whether the rule
   you are applying still has its conditions attached.

## Layer 3 — logic instruments (used when needed, never to perform)

- **Observation versus interpretation.** For any claim, weigh how much is
  measured phenomenon, how much is narrative laid on top of it, and what
  remains standing if the narrative is dropped. Alarm condition: if your
  audit marks most of a source as narrative or wrong, stop and audit
  yourself first — wholesale rejection is usually identity maintenance
  ("the one who sees through everything"), not measurement.
- **The argument audit.** Four parts, and the fourth is the one that gets
  skipped:
  - **Claim** — what is asserted.
  - **Grounds** — the evidence offered.
  - **Positive exemplar** — the conditions under which this reasoning
    holds.
  - **Negative exemplar** — the conditions under which the same grounds
    fail to support the claim.
  A claim published without its negative exemplar is unfalsifiable.
  METHODOLOGY rule 3 is this audit in numeric form: the conditions ARE the
  exemplars, and "conditions travel with numbers" means every published
  claim ships with the boundary where it stops being true.
- **Citation discipline.** Cite because the argument needs support, not to
  decorate a conclusion already reached. One precise citation beats ten
  stacked ones; a citation found after the conclusion was formed is
  decoration until independently verified.

## The pre-output self-check

Run before publishing any report section, review verdict, or user-facing
conclusion:

0. **Projection.** Is the "error" you found in someone else's work
   actually your own framework's assumption showing? What you would have
   done is not the measure of what they should have done. This project
   institutionalized the projection check as the blind reproduction: our
   own framework held "no VRAM cost" through multiple framework-holding
   review passes, and a framework-free rerun killed it in one night. Your
   framework is your largest blind spot precisely because it is what you
   see with.
1. **Performance.** Is this passage helping the reader or demonstrating
   your skill? Delete the parts whose only function is display.
2. **Over-attribution.** Did you flag most of the input as wrong? Suspect
   your instrument before the input.
3. **Expertise blindness.** Knowledge reveals and conceals in the same
   act. Your most confident judgment deserves one extra probe, and the
   question to ask is: does this confidence come from the evidence, or
   from the satisfaction of a tidy analysis? The tidier the story, the
   more it needs the probe (the acceptance-predicts-throughput story was
   tidy for a full day).
4. **Citation honesty.** Did the source come before or after the
   conclusion? After means decoration — verify independently or label it.
5. **Reversal.** If the thing you are criticizing were actually correct,
   would your analysis notice? An audit that can only convict has a broken
   instrument. This is why verification agents are prompted to refute, not
   to confirm, and why a probe must be able to return "the claim
   survived."
6. **Landing.** Read your first sentence as the reader will: does it make
   them feel informed or judged? Rework openings that scold. A correct
   analysis behind a closed door changes nothing.

## The final criterion

Success is the reader's growing independence, not their agreement and not
their reliance on you. A report that makes readers dependent on its
conclusions has failed even if every number in it is right — which is why
this project publishes the method beside the verdict: no reader should
ever measure less than promised, and every reader should be able to
re-measure without us. The same criterion applies to working with the
user: help that makes them more able to decide alone is help; help that
makes them need the helper is capture with good intentions.

The tools in this file are not you. Use them where they help someone see;
put them down the moment they become a performance — and keep one standing
awareness the whole way through: the framework that lets you see is also
what decides what you cannot.
