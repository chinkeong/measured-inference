# measured-inference

Read `AGENTS.md` — it is the entrypoint for all agents, including Claude Code.
It is a router: the invariants, plus a table saying which single file to open
for the situation you are in. When the user names a model and asks for a report
or field guide, read `skills/field-guide/SKILL.md` and follow it, then load only
`skills/field-guide/stages/stage-N.md` for the stage you are executing. (These
are plain files in this repo, not installed Claude Code skills — read them, do
not try to invoke them.)
