# ADR-0025: Unused design components are surfaced, not enforced

Status: proposed 2026-10-05 (revised draft for owner review). Replaces the
2026-10-03 draft of the same number, which proposed element ids, a
`data-design` presence check, a side-by-side evaluator pass and fidelity
levels. Those are dropped below, with reasons.

## Context

Users bring their own design source (a Figma file, screenshots, a live site)
and expect it to shape the product their PRD describes. The source is usually
drawn for some other product, so part of it has no obvious place in ours.

The `study-gallery` build shows where that goes wrong. The source was a
community to-do app kit. After the build the owner compared the shipped
screens with the kit and found them thin. From the files:

- **`/gatekit:design` extracted the detail.** `spec/02-design.md` lists a
  `HeroCard` component (primary fill, `radius.hero`, `shadow.hero`, Figma node
  `101:137`), an `IconTile` component with four pastel fills, `StatusPill`,
  and every colour token.
- **The loss happened between `02-design.md` and `02-screens.md`.** The
  screens file never names `HeroCard` or `IconTile`. The kit's hero card shows
  "today's tasks 85 %"; the PRD had no matching data, so no screen took the
  card, and nobody was asked. In code, `shadow-hero` is used once and the
  pastel fills once.
- **Workers used emoji as icons** (♥ 👍 💬 👁 🖼 👥 🗑). The kit uses one
  filled icon set. No rule recorded that, and `tokens.py` checks colour
  literals only (ADR-0008), so nothing objected.
- **The prototype gate did not catch it.** `/gatekit:mockup` Step 7b shows a
  clickable prototype before the build (ADR-0017 decision 4). But the
  prototype is built from `02-screens.md`, so a component missing there is
  missing from the prototype too, and the user was not shown the source
  beside it.

What the owner did next matters as much as the gap. Given a free hand, the
owner did not ask for the kit to be followed more closely everywhere. A home
button added in the kit's style was removed as out of place; the kit's own
back arrow was kept. The owner wanted to **choose** which parts of the source
to carry over, and the process never showed them the choice.

Two earlier decisions bound this one:

- **ADR-0011** already injects the `02-screens.md` row for each screen a task
  names into the worker prompt (decision 3). A component listed on a screen
  therefore reaches the worker. The same ADR rejected a gate that checks built
  screens against the spec, because mechanically checking layout fidelity
  produces mostly false failures.
- **ADR-0024** cut the Stop gate's cost after the owner, facing 145 minutes of
  contract runs in one session, asked for the hooks to be deleted. Any new
  criterion has to earn its runtime.

The evidence is one project. This ADR therefore adds visibility and one cheap
rule, and no new enforcement.

## Decision

### 1. `spec validate` warns about design components no screen uses

`02-design.md` already names each component in its Components table, and
`02-screens.md` already has a Components table with a "Used on" column. A new
check compares the two: every component named in `02-design.md` that does not
appear in `02-screens.md` is reported as `warn`, one finding per component,
naming it.

A component the user decides not to use is listed under a new
`## Not carried over` section in `02-design.md`, one row per component with a
one-line reason. A listed component is not reported.

The finding is `warn` only, never `fail`. It exists so that dropping a
component is a decision someone made, not something that happened.

Patterns (`P<n>` rows) are out of this check. Their "Applies to" cell is
often `all`, which would satisfy any check without saying anything.

### 2. The prototype gate shows the source and asks about unused components

`/gatekit:mockup` Step 7b, before its existing question 4 ("does this
prototype fully cover what you want built?"), does two things when a design
source was read:

- It shows each prototype screen next to its closest source capture from
  `02-design.md`'s Sources table, so the user compares the two directly.
- It lists the components the check in 1 would report, and for each asks one
  thing: use it, and on which screen, or leave it out. For a component whose
  role needs data the PRD does not have (the kit's progress card needs a
  progress figure), it says so and offers two choices: map it to something
  the PRD already has, or leave it out. Adding data to the PRD is not offered
  here. It routes to `/gatekit:interview` like any other missing feature, so
  the study's rule that new ideas are proposed, not built, still holds.

"Use it" writes the component into `02-screens.md` for the named screen, so
ADR-0011's injection carries it to the worker. "Leave it out" writes the row
under `## Not carried over`. Either answer clears the warning in 1.

This uses the one human checkpoint the pipeline already has. It adds no new
stop.

### 3. The worker prompt names the source capture

Where ADR-0011 injects a screen's row, it also adds the path of that screen's
closest source capture, when `02-design.md` records one. One line per screen.
The worker can open the image; nothing checks that it did.

### 4. The tokens gate rejects emoji used as icons when the source has an icon set

`/gatekit:design` records whether the source uses a single icon set, in one
line under Design patterns. When it does, `tokens.py` also fails on emoji
characters in the task's write scope, with the same verdict rules and exit
codes it uses for colours. String literals meant as user-visible text (a toast
saying "🎉") are the expected false positive. They are listed in
`spec/tokens.json` under `allow.emoji`, the same way `allow.color` already
exempts colour values the gate would otherwise reject.

This is the only new enforcement, and it is cheap: one scan the gate already
does per task, with no runner or browser.

## Dropped from the first draft

- **Element ids (`D-HeroCard`).** The Components and Patterns tables already
  name everything. A second naming scheme adds bookkeeping without new
  information.
- **A `data-design` presence check in E2E.** An attribute on an empty `div`
  passes it, so it measures whether the attribute was written, not whether the
  component was built. It also adds markup to the product.
- **A side-by-side evaluator pass in `/gatekit:verify`.** Subjective,
  expensive, and the kind of check ADR-0011 rejected for producing false
  failures. It also runs against ADR-0024's lesson on contract cost.
- **Fidelity levels (`mood` / `components` / `close`).** With 1 a warning and
  2 a question, there is nothing left for a level to tighten. It would be a
  setting with no effect.
- **Widening the PRD from the design step.** The first draft let the role
  mapping amend `01-prd.md`. Here a missing role routes to the interview like
  any other missing feature.

## Consequences

- A design component can no longer disappear between the design spec and the
  screens without anyone seeing it. It is either placed on a screen or listed
  as not carried over, and the user made that call at the prototype.
- The prototype round gets longer by one list and one comparison per screen,
  only when a design source was read.
- Workers see the source image path. Whether that improves first-pass
  fidelity is not measured here.
- Projects with no design source see no change. Existing projects get the
  warning in 1 on their next `spec validate`, and can clear it by listing
  components under `## Not carried over`.
- Contract runtime does not change: 1 and 2 run before the build, and 4 runs
  inside a task gate that already exists.

## Evidence to collect before accepting

The case rests on one project. Before this moves to accepted, count, for each
project in the current study cohort that brings a design source, how many
components in `02-design.md` never appear in `02-screens.md`. If unused
components recur across projects, accept. If `study-gallery` turns out to be
the only case, keep this proposed.

## Open questions

- How should "closest source capture" be chosen when a screen has no obvious
  counterpart? Probably the user names it during the prototype round, or the
  line is left out.
- Does emoji detection need a narrower scope than the task's write scope, for
  example only `.tsx`/`.jsx`/`.vue`/`.svelte` files?
