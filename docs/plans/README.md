# Plans

Design and implementation plans, tracked in git deliberately.

Each is named `YYYY-MM-DD-topic[-design|-plan].md` by the date it was written,
not the date the work landed. A plan is a record of what was decided and why,
so it is left as written once its work ships rather than being tidied up to
match the result — where the two differ, that gap is usually the interesting
part.

## These were ignored until 2026-08-24

`.gitignore` carried `docs/plans/` while thirteen plans were committed into it
with `git add -f`. The rule and the practice had disagreed for months, and the
cost was not theoretical: a plan branch reviewed in August turned out to be
based two commits behind `main`, and three of its "corrected" line references
were stale rather than wrong. A directory that is half-ignored is a directory
where that is hard to notice.

The rule is gone and the whole directory is tracked. Nothing here needs `-f`.

## Line references go stale

Plans in here cite exact line numbers, which are accurate on the day they are
written and drift afterwards. Two habits help:

- **Cite a symbol alongside the number** — `seed_default_rules`
  (`exclusion_service.py:154`) survives a refactor that `:154` alone does not.
- **Rebase before trusting a plan branch's references.** Check
  `git merge-base main <branch>` first. A stale base looks exactly like
  carelessness and has a completely different fix.
