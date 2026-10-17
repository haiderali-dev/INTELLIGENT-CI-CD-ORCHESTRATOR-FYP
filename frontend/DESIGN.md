# Frontend design

Status: **approved** on 2026-10-15 by the user, as written (T6.1, drafted 2026-10-13). Screens
from T6.3 onward are built to this file. A change to it after approval is a new decision in
`docs/decisions.md`, not a silent edit.

`python scripts/verify.py --phase 6` checks this file against Part 4.7.2. It recomputes the
contrast and colour distances below from the tables in section 2, so a colour edited here without
re-measuring fails the gate.

## 1. Subject and audience

A queue and release control room for a four-person university team and their supervisor, used on
a laptop during a live demo.

What follows from that:

- **It is shown, not browsed.** The laptop is usually on a projector or turned toward a table.
  Most people reading it are two or three metres away and not the one driving. Text, numbers and
  states have to survive that distance and a washed-out projector image.
- **The demo is a script.** Ask an assistant for a deploy, approve it, watch the job enter the
  queue above lower-priority work, watch it run, read the result. Each screen is judged by how
  well it carries its step of that script.
- **The supervisor's question is "why is that job first?"** The answer is the score. That is why
  the score is the one thing the interface makes memorable.
- **Staging only.** The product refuses production deploys, and the shell says Staging on every
  page, so nobody in the room has to wonder.

## 2. Palette

Every value here was measured, not judged by eye. Method and results are under Measurements.

### Named values

Six named values. Every other colour on screen is a score bar or build-state colour from the
tables below, or a mix of these six.

| Name | Light | Dark | Role |
| --- | --- | --- | --- |
| Ground | `#eef1f4` | `#0d1014` | Page background, sidebar, hovered table rows |
| Panel | `#ffffff` | `#171b21` | Thread, tables, preview and dialogs: every surface that holds content or a chart |
| Ink | `#111418` | `#e8ebef` | Text, the primary button, focus rings, the inherited-score tick |
| Graphite | `#4a5361` | `#a9b2be` | Secondary text, control borders, axis text, the neutral states |
| Spruce | `#127a6b` | `#7bd1ba` | Freestyle Assistant only: its sidebar marker, header rule and glyph |
| Plum | `#633f5f` | `#e3b6fe` | Pipeline Assistant only: its sidebar marker, header rule and glyph |

Derived rather than new: **Rule**, the 1px divider between rows and regions, is
`color-mix(in oklab, Graphite 25%, Panel)` in light (`#ced1d5`) and 30% in dark (`#3e434b`). It is
never the only edge of a control. Inputs and secondary buttons are outlined in Graphite.

There is no brand hue and no "primary" colour. The primary action is Ink: a near-black button in
light mode and a near-white one in dark.

Dark mode is chosen, not inverted. Every value has its own dark step, measured against the dark
Panel. **The demo default is light**, because projectors wash dark themes out. The user menu
offers Light, Dark and System.

### Score bar colours

Data colours. They fill score bar segments and their legend keys and nothing else. Text never
wears them.

| Factor | Weight | Light | Dark |
| --- | --- | --- | --- |
| Urgency | 0.5 | `#187eee` | `#187eee` |
| Dependency | 0.3 | `#d94787` | `#c23492` |
| Execution time | 0.2 | `#4c35b5` | `#6859da` |
| Aging | bonus, at most 0.15 | `#1594ac` | `#0ca3be` |

The order is the formula's, 0.5U + 0.3D + 0.2T and then aging, and the hues never move: blue is
urgency on every page.

### Build-state colours

Reserved for build states. A state is always an icon and a word, and the colour is the third cue.

| State | Icon | Light | Dark |
| --- | --- | --- | --- |
| Succeeded | check in a circle | `#069c07` | `#0ca30c` |
| Failed | cross in an octagon | `#a51f1e` | `#f76046` |
| Unstable | exclamation in a triangle | `#b07800` | `#fab219` |
| Running | open ring, turning (still under reduced motion) | Graphite | Graphite |
| Queued | clock | Graphite | Graphite |
| Aborted | slashed circle | Graphite | Graphite |
| Not built | dashed circle | Graphite | Graphite |

Running is deliberately not blue. Blue is urgency, and a running build beside a score bar would
read as "urgent".

Health is not a build state. The AI provider's status, a service's reachability in the catalog and
the plugin's availability use Ink or Graphite with an icon and a word, never green or red.
Destructive actions are not red either: they say exactly what they remove and ask for
confirmation.

### Measurements

Contrast is WCAG 2.2 relative luminance. ΔE is the distance in OKLab ×100. "CVD" is the same
distance after simulating protanopia and deuteranopia (Machado, Oliveira and Fernandes 2009, full
severity), worst of the two. The score bar was validated with the dataviz skill's
`validate_palette.js`, which checks a lightness band, a chroma floor, adjacent CVD ΔE ≥ 8, adjacent
normal ΔE ≥ 15 and 3:1 against the surface. Measured 2026-10-13.

Contrast (WCAG):

| Pair | Use | Needs | Light | Dark |
| --- | --- | --- | --- | --- |
| Ink on Panel | Body text | 4.5:1 | 18.47:1 | 14.45:1 |
| Ink on Ground | Body text on the page | 4.5:1 | 16.29:1 | 15.95:1 |
| Graphite on Panel | Secondary text, control borders | 4.5:1 | 7.77:1 | 8.06:1 |
| Graphite on Ground | Secondary text on the page | 4.5:1 | 6.86:1 | 8.90:1 |
| Panel on Ink | Primary button label | 4.5:1 | 18.47:1 | 14.45:1 |
| Spruce on Panel | Freestyle accent | 3:1 | 5.22:1 | 9.60:1 |
| Plum on Panel | Pipeline accent | 3:1 | 8.73:1 | 10.19:1 |
| Spruce on Ground | Freestyle sidebar marker | 3:1 | 4.61:1 | 10.60:1 |
| Plum on Ground | Pipeline sidebar marker | 3:1 | 7.70:1 | 11.25:1 |
| Succeeded on Panel | State icon | 3:1 | 3.64:1 | 5.15:1 |
| Failed on Panel | State icon | 3:1 | 7.46:1 | 5.53:1 |
| Unstable on Panel | State icon | 3:1 | 3.80:1 | 9.42:1 |
| Succeeded on Ground | State icon in a hovered row | 3:1 | 3.21:1 | 5.68:1 |
| Failed on Ground | State icon in a hovered row | 3:1 | 6.58:1 | 6.10:1 |
| Unstable on Ground | State icon in a hovered row | 3:1 | 3.35:1 | 10.39:1 |
| Urgency on Panel | Segment | 3:1 | 3.99:1 | 4.33:1 |
| Dependency on Panel | Segment | 3:1 | 4.04:1 | 3.46:1 |
| Execution time on Panel | Segment | 3:1 | 8.45:1 | 3.32:1 |
| Aging on Panel | Segment | 3:1 | 3.58:1 | 5.76:1 |
| Urgency on Ground | Segment in a hovered row | 3:1 | 3.52:1 | 4.77:1 |
| Dependency on Ground | Segment in a hovered row | 3:1 | 3.56:1 | 3.81:1 |
| Execution time on Ground | Segment in a hovered row | 3:1 | 7.46:1 | 3.66:1 |
| Aging on Ground | Segment in a hovered row | 3:1 | 3.16:1 | 6.35:1 |
| Rule on Panel | Dividers only | none | 1.53:1 | 1.74:1 |

The worst text pair is Graphite on Ground in light mode, 6.86:1. No score bar colour is closer
than 17.7 ΔE to a state colour in normal vision (Dependency and Failed, light), or 10.8 under CVD
(Dependency and Succeeded, light).

Score bar, validator:

- Light, on `#ffffff`: all five checks pass. Worst adjacent pair is execution time and dependency,
  CVD ΔE 15.3. Worst adjacent normal ΔE is 25.2.
- Dark, on `#171b21`: all five checks pass. Worst adjacent pair is execution time and dependency,
  CVD ΔE 11.9 and normal ΔE 20.0.

Colours with different jobs that can share a screen (normal ΔE / CVD ΔE):

| Pair | Where they meet | Light | Dark |
| --- | --- | --- | --- |
| Failed / Unstable | a list of results | 19.5 / 14.6 | 19.3 / 13.7 |
| Failed / Succeeded | a list of results | 34.1 / 12.2 | 33.2 / 7.1 |
| Unstable / Succeeded | a list of results | 19.2 / 2.5 | 27.6 / 11.3 |
| Failed / Dependency | a run card: state and score bar | 17.7 / 16.6 | 19.2 / 19.3 |
| Succeeded / Aging | a run card: state and score bar | 19.8 / 18.0 | 20.9 / 19.2 |
| Spruce / Plum | the sidebar, which lists both assistants | 18.4 / 10.1 | 19.1 / 8.7 |
| Spruce / Succeeded | Freestyle header above a passed run | 16.2 / 14.6 | 22.7 / 20.7 |
| Spruce / Aging | Freestyle header above a score bar | 11.2 / 10.8 | 15.9 / 14.9 |
| Plum / Execution time | Pipeline header above a score bar | 15.3 / 14.7 | 31.0 / 28.4 |
| Plum / Failed | Pipeline header above a failed run | 15.2 / 10.3 | 25.7 / 23.6 |

Known limits, kept on purpose:

- **Succeeded and Unstable in light mode** are 19.2 apart in normal vision but 2.5 for a red-green
  colour-blind reader. Both must clear 3:1 on white and on Ground, which puts them at nearly the
  same lightness. The best green found that separates them reached only 7.3, and it moved toward
  Spruce and Aging. The icon shape and the word tell them apart, as they do for every state.
- **Failed and Succeeded in dark mode** are 7.1 apart under CVD. That is in the 6 to 8 band, which
  is acceptable only with a second cue, and the icon and word are that cue.
- **Spruce and Aging in light mode** are 11.2 apart. They never mark the same kind of thing:
  Spruce is a 4px rule in a page header, and Aging is a bar segment next to a legend.

## 3. Type

Two families, both from IBM Plex, self-hosted so the demo never waits on a font CDN.

- **IBM Plex Sans** for everything that is not code: headings, body, tables, buttons, figures.
  Weights 400 and 600 only. It was drawn for technical interfaces, it tells 0 from O and 1 from l
  from I (job names and build numbers are full of them), and it has tabular figures.
- **IBM Plex Mono** inside code views only: the Jenkinsfile, `config.xml`, the spec YAML, console
  logs and diffs. Never for labels, job names, build numbers or hashes outside a code view.

Scale (16px root):

| Token | Size / line height | Use |
| --- | --- | --- |
| `text-xs` | 12 / 16 px | Chart axis ticks and keyboard hints only |
| `text-sm` | 14 / 20 px | Table cells, chips, secondary text |
| `text-base` | 16 / 24 px | Body, chat messages, form fields, buttons |
| `text-lg` | 20 / 28 px | Section headings, dialog titles |
| `text-xl` | 24 / 32 px | Page headings, the overview's secondary figures |
| `text-hero` | 40 / 48 px | The overview's one lead figure, jobs waiting |

- Prose (messages, explanations, dialog text, empty states) is capped at 68ch, under the
  80-character limit at every width.
- Every number that sits in a column or changes while you watch uses tabular figures: rank,
  score, estimate, wait, durations, timers. A lone large figure keeps proportional figures.
- Scores print with three decimals everywhere (0.820), as Appendix C does (0.633, 0.650).
- Headings and table headers are sentence case at normal tracking. The only capitals are the
  urgency levels HIGH, MEDIUM and LOW. They are capitals in the data, in the report and in
  4.7.4's approval sentence, so they keep one name everywhere.

## 4. Layout

Key to the sketches:

- `>` is the current page, shown as a 3px Ink bar.
- `[S]` and `[P]` are the Freestyle (Spruce) and Pipeline (Plum) glyphs.
- `#` is the 4px accent rule in the assistant's colour.
- `U D T A` are score bar segments: urgency, dependency, execution time and aging. A space is the
  2px gap, `.` is the empty track and `:` marks an inherited score. The sketches are not to scale;
  section 6 is.
- `(v) (x) (!) (o) ( )` are the state icons: succeeded, failed, unstable, running, not started.
- `[Label]` is a button or a chip.

**Shell.** A left sidebar names every page, with the two assistants as separate entries in their
own colours and a footer that says Staging and who is signed in. Under 768 px it folds into a menu
button and Staging moves to the top bar.

### Assistant workspace

Chats, thread and preview side by side, so the conversation and the exact jobs it will create are
visible at the same time. Under 1280 px the preview becomes a drawer and under 768 px a bottom
sheet.

```text
+----------------+----------------+-------------------------------------+--------------------------+
| Overview       | Chats          |# Freestyle Assistant                | Preview                  |
|>[S] Freestyle  |                |# Creates chained freestyle jobs     | Spec  Config  Checks     |
| [P] Pipeline   | Deploy payment |# on staging, from plain English.    | Explanation              |
| Queue          | Rerun tests    |-------------------------------------|--------------------------|
| Jobs and runs  | Last deploy?   | You                                 | service: payment-service |
| Analytics      |                | Deploy payment-service from main,   | branch: main             |
| Service catalog|                | high priority.                      | environment: staging     |
| Admin          |                |                                     | urgency: HIGH            |
|                |                | [S] Freestyle Assistant             |                          |
|                |                | +---------------------------------+ | Checks                   |
|                |                | | Service      [payment-service]  | | (v) Understood           |
|                |                | | Branch       [main]             | | (v) Planned              |
|                |                | | Environment  [staging]          | | (v) Rendered             |
|                |                | | Urgency      [HIGH]             | | (v) Validated            |
|                |                | | [Generate]  [Edit]              | |                          |
|                |                | +---------------------------------+ | Creates 3 jobs and       |
|                |                | +---------------------------------+ | starts fs-payment-       |
|                |                | | 1st in queue              0.820 | | service-build on main    |
|                |                | | UUUUUUUUUUUUU DDDD TTT A....... | | at HIGH priority.        |
|                |                | | Waiting for a free executor     | |                          |
|                |                | | (v) Build  (o) Test  ( ) Deploy | | [Approve and run]        |
|                |                | +---------------------------------+ |                          |
| Staging        | [New chat]     |-------------------------------------|                          |
| you@group04    |                | Message the assistant      [Send]   |                          |
+----------------+----------------+-------------------------------------+--------------------------+
```

At 360 px the thread is the page, and the preview is a bottom sheet with a one-line summary:

```text
+----------------------------------+
| [=]  Freestyle Assistant   [S]   |
|----------------------------------|
| You                              |
| Deploy payment-service, high     |
| [S] Freestyle Assistant          |
| +------------------------------+ |
| | 1st in queue           0.820 | |
| | UUUUUUUUUUUU DDDD TTT A..... | |
| +------------------------------+ |
|----------------------------------|
| Preview: 3 jobs, all checks pass |
| Message the assistant    [Send]  |
+----------------------------------+
```

The Pipeline Assistant is the same layout with Plum, its own glyph, header and empty state, and a
Preview that shows the Jenkinsfile instead of `config.xml`.

### Queue

One table ranked by score, in which every row explains its own rank with a score bar and, when it
has one, its blocked reason. Under 768 px each row becomes a stacked block with the bar on its own
line.

```text
+------+--------------------------+-----------+---------+----------------------------+----------+------+------------------------------------+
| Queue                                                                                                     5 waiting   Optimizer on   Live |
| Ranked by score, highest first. Each bar shows what its score is made of.                                                                 |
| Key: [U] Urgency  [D] Dependency  [T] Execution time  [A] Aging      [Show the numbers]                                                   |
+------+--------------------------+-----------+---------+----------------------------+----------+------+------------------------------------+
| Rank | Job                      | Type      | Urgency | Score                      | Estimate | Wait | Blocked reason                     |
+------+--------------------------+-----------+---------+----------------------------+----------+------+------------------------------------+
|    1 | fs-payment-service-build | Freestyle | HIGH    | UUUUUUUUU DDD TT A.. 0.820 |  1m 20s  |  6m  |                                    |
|    2 | fs-payment-service-test  | Freestyle | HIGH    | UUUUUUUUU DD TT A.:. 0.820 |  2m 00s  |  6m  | Waits for fs-payment-service-build |
|    3 | pl-auth-service          | Pipeline  | HIGH    | UUUUUUUUU T......... 0.580 |  3m 05s  |  2m  |                                    |
|    4 | fs-auth-service-build    | Freestyle | MEDIUM  | UUUUU DDD TT........ 0.570 |  1m 10s  |  3m  |                                    |
|    5 | nightly-report           | Freestyle | LOW     | UUU TTT AAA......... 0.480 |     40s  | 17m  |                                    |
+------+--------------------------+-----------+---------+----------------------------+----------+------+------------------------------------+
```

Row 2 is the Appendix C case: its own score is lower, it inherits its group's 0.820, and the `:`
tick shows where the inherited score sits. Row 5 is LOW but has waited 17 minutes, and its aging
segment is the widest on the page.

```text
+----------------------------------+
| Queue        5 waiting   Live    |
|----------------------------------|
| 1  fs-payment-service-build      |
|    UUUUUUUUUU DDD TT A... 0.820  |
|    Freestyle  HIGH  1m 20s  6m   |
|----------------------------------|
| 2  fs-payment-service-test       |
|    UUUUUUUUUU DD TT A.:.. 0.820  |
|    Freestyle  HIGH  2m 00s  6m   |
|    Waits for fs-payment-service- |
|    build                         |
+----------------------------------+
```

### Overview

One sheet led by a single large figure, the number of jobs waiting, then my active runs with their
score bars and the latest results, so the room sees what is happening now without opening another
page.

```text
+----------------+---------------------------------------------------------------------------+
|>Overview       | Overview                                     AI provider: Groq, answering |
| [S] Freestyle  |---------------------------------------------------------------------------|
| [P] Pipeline   | 5                 2                      1 of the last 10                 |
| Queue          | jobs waiting      my active runs         runs failed                      |
| Jobs and runs  |---------------------------------------------------------------------------|
| Analytics      | My active runs                                                            |
| Service catalog| fs-payment-service-build  1st in queue  UUUUUUUUUU DDD TT A... 0.820      |
| Admin          | pl-auth-service           (o) Running, Test stage, 1m 12s                 |
|                |---------------------------------------------------------------------------|
|                | Recent results                                                            |
|                | (v) Succeeded  fs-auth-service-deploy-staging   2m 10s  14:02             |
|                | (x) Failed     pl-payment-service, Test stage   1m 05s  13:55  [Explain]  |
|                | (!) Unstable   fs-payment-service-test          1m 40s  13:41             |
+----------------+---------------------------------------------------------------------------+
```

"5" is the hero figure (`text-hero`). "2" and "1 of the last 10" are `text-xl`. When the rule
parser is answering instead of the model, the provider line says so in words: "AI provider: rule
parser (Groq unreachable)".

## 5. Principles

1. **The score bar is the one loud thing.** Wherever a score appears, the same bar appears: four
   segments in a fixed order and fixed hues, on one fixed scale, with the score as a number beside
   it. It is the only colour that is neither a build state nor an assistant's mark, so the eye
   goes to it first. And it answers the supervisor's question where it is asked: the queue
   explains each rank in its own row, and the run card explains its own wait.
2. **A state is a word first.** Every build state is an icon and a word. Colour is the third cue,
   never the only one. State colours mean build states and nothing else: no green "online" dots,
   no red delete buttons.
3. **Readable from the back of the room.** The interface is projected. Body text is 16px, figures
   are semibold with tabular digits, and every text pair clears 4.5:1 (the worst is 6.86:1). No
   meaning sits only in a hairline or only on hover, and light is the default theme.
4. **Say exactly what will happen, in the same words.** The approval names the jobs, the branch
   and the priority. The button says Approve and run, the toast says Run started and the run card
   says Running: one name per action through the whole flow. An error says what happened and how
   to fix it.
5. **Two assistants, never confused.** Freestyle is Spruce with a chain glyph and Pipeline is Plum
   with a stage-track glyph. Each has its own sidebar entry, page header, empty state and composer
   placeholder. The accents mark identity only: no Spruce buttons, no Plum charts.

## 6. The score bar

```text
 UUUUUUUUUUUUUUUUUUUU DDD TTT A...:......!.....  0.820 inherited
 ^                                ^      ^    ^
 0                                0.820  1.0  1.15
```

That is the test job from the queue, to scale: urgency 0.500, dependency 0.100, execution time
0.100 and aging 0.050, own score 0.750, inheriting its group's 0.820.

- **Scale.** Fixed from 0 to 1.15, the most a job can score (0.5 + 0.3 + 0.2 + 0.15), on every
  page, so a bar can be compared with any other. A Graphite tick at 1.0 marks the ceiling of the
  three weighted factors; only aging goes past it.
- **Segments.** Each width is weight × factor. The weights come from the queue API's `weights`,
  which is the plugin's own, and are never hard-coded in the UI. A factor of zero draws nothing and
  leaves no gap. A non-zero segment narrower than 2px is drawn at 2px; the numbers stay exact.
- **Marks.** A 2px Panel gap between segments, never a stroke. The start is square and the data
  end has a 4px radius. The empty track is a 1px Rule line out to 1.15.
- **Inherited score.** When the effective score is above the job's own (it inherits from its
  group: Appendix C has own 0.633 and effective 0.650), a 2px Ink tick marks the effective score.
  The number beside the bar is the effective score, and the label says it is inherited.
- **The number.** Ink, tabular figures, three decimals, to the right of the bar.
- **Sizes.** Queue row 160 × 12 px. Run card full width (at most 480 px) × 16 px, with a one-line
  legend under it giving each contribution. Analytics 20 px, with an axis at 0, 0.5, 1.0 and 1.15.
- **Reading it without colour.** The bar is `role="img"`, with an accessible name such as "Score
  0.820, inherited from its group. Own score 0.750: urgency 0.500, dependency 0.100, execution time
  0.100, aging 0.050." Hover or focus shows the same as a tooltip. The queue's Show the numbers
  switch adds the four contributions as columns, and every Analytics chart has Show as table. In
  forced-colours mode the four numbers print beside the bar.
- **When there is no ranking.** If the plugin cannot be read, as on the baseline controller, the
  bar is replaced by "Ranking unavailable" and the reason, never by an empty bar. When the
  optimizer is off (the observe-only arm), the bars still show the score, and the page header
  says "Optimizer off: Jenkins' own order".
- **Motion.** On first load of the queue the bars grow from 0 once, in 240 ms with ease-out. Live
  updates jump straight to the new value. Under reduced motion nothing moves.

## 7. Shape, space and motion

- **Radius follows role:** 0 for tables, panels and the page; 2px for buttons, inputs and chips;
  4px for the score bar's data end; 8px for floating layers (menus, popovers, dialogs, drawers,
  toasts). This replaces shadcn/ui's single `--radius`.
- **Elevation:** blocks in the flow have no shadow. Floating layers have one shadow in light mode,
  `0 8px 24px rgb(17 20 24 / 0.16)`, and in dark mode a Rule border instead, because shadows do
  not read on a dark ground.
- **Borders:** Rule (1px) between rows and regions; Graphite (1px) around inputs and secondary
  buttons.
- **Spacing:** a 4px base, used as 4, 8, 12, 16, 24, 32 and 48. Table rows are 40px tall, and
  every touch target under 768 px is at least 44px.
- **Breakpoints:** 360 px is the minimum. At 768 px the preview becomes a bottom sheet, tables
  become stacked rows and the sidebar becomes a menu. At 1280 px the preview becomes a drawer.
  1440 px is the reference desktop.
- **Motion:** one page-load sequence (content fades in over 120 ms, and the queue's bars grow
  once) and feedback on what the user did (a pressed button, a toast sliding in over 160 ms, a new
  message fading in). Nothing loops except the running icon, which stops under reduced motion.
- **Icons:** Lucide, which shadcn/ui already uses: 16px inline and 20px in the sidebar, with a
  2px stroke. The state icons were picked for different outlines (circle, octagon, triangle,
  slashed circle, dashed circle, clock, open ring), so they differ in shape before they differ in
  colour.

## 8. Accessibility and copy floor

- **Contrast:** WCAG 2.2 AA, measured in section 2. Text is at least 4.5:1, and every graphic that
  carries meaning is at least 3:1 on both the surfaces it can sit on.
- **Focus:** a 2px Ink outline with a 2px offset on everything interactive, never removed, at
  18.47:1 (light) and 14.45:1 (dark) on Panel.
- **Live regions:** the thread's message list is `aria-live="polite"`, so each new assistant
  message is announced once. Progress steps announce their result: "Validated" or the exact
  error.
- **Keyboard:** the whole approval works with the keyboard alone (a 4.7.6 Playwright flow). In the
  composer, Enter sends and Shift+Enter adds a line.
- **Reduced motion:** `prefers-reduced-motion` turns off the page-load sequence, the bar growth
  and the turning running icon.
- **360 px:** no horizontal page scroll. Tables reflow into stacked rows, and code views scroll
  inside their own box.
- **Copy:** sentence case, active verbs, one name per action. Errors say what happened and how to
  fix it, and empty states invite an action: the assistant's empty state has one sentence on what
  it creates, four example commands to click and the services it knows.

## 9. Review against the generic traits

Part 4.7.2 lists four traits that read as generic. The plan was checked against each one, and this
is what changed.

| Trait | What in the plan matched | What changed, and why |
| --- | --- | --- |
| Cream background, serif display face, terracotta accent | The best-scoring score bar set from the dataviz reference palette was aqua, blue, orange and violet. Its orange, `#eb6834`, is the terracotta accent on a light ground in all but name. It was also only 10.8 ΔE from the failure red. The ground (cool grey) and type (IBM Plex Sans) never matched. | Orange is out of the bar. The slots are blue, magenta, violet and cyan, re-stepped until the bar passes the validator in both modes. Dependency, the factor closest to the failure colour, is now 17.7 (light) and 19.2 (dark) away from it. Aqua went too: it was 10.0 from the success green. |
| Identical rounded cards, one shared radius, one soft grey shadow | The stack this spec names, shadcn/ui, defaults to exactly this: one `--radius` for every component, and a Card with a soft shadow. Built as named, the thread (messages, intent card, run card) and a four-tile overview would have been a stack of identical cards. | Radius follows role (section 7). Only floating layers have a shadow, because only they float. Messages are not boxed. The intent card and run card are Rule-bordered blocks with no shadow, and they differ in content and height. The overview is one ruled sheet led by one figure, not four tiles of equal weight. |
| Gradient washes used as decoration | Nothing in the plan. Recharts' area chart examples use gradient fills, so it would have arrived with the chart library. | No gradients anywhere. Area fills in Analytics are flat 10% tints of the series colour. |
| All-caps eyebrows, middle-dot meta strings, arrows on buttons, monospace small labels | Two near misses. The run card's facts are naturally written as one dotted line ("payment-service · main · HIGH"). And job names, build numbers and commit hashes look like code, which invites monospace. | Facts are labelled fields ("Branch main", "Urgency HIGH"). Job names, build numbers and hashes are Plex Sans with tabular digits, and Plex Mono appears only inside code views. Headings and table headers are sentence case at normal tracking. Buttons name the action with no arrow: Approve and run, Generate, Edit. A link out to Jenkins says Open in Jenkins and carries the external-link icon with "opens in a new tab" for screen readers. That icon does a job, and decoration would not. |

Three changes came from measuring rather than from the list:

- **Running** was blue in the first plan. Blue became urgency's segment, so Running moved to
  Graphite with a turning ring.
- **Light-mode failure red** moved from `#d03b3b` to `#a51f1e`. Next to the light dependency
  magenta, the brighter red was 10.1 ΔE away. And at the same lightness as unstable amber, it was
  4.9 apart for a colour-blind reader.
- **Light-mode success green** moved from `#0ca30c` to `#069c07`. This file's own check in
  `verify.py` found the first green at 2.96:1 on Ground, the colour of a hovered row. The first
  measurement had checked state colours on Panel only.

## 10. What approval covers

Please look hardest at these, because they are the choices most worth disagreeing with:

1. Six named values plus four score bar colours and three state colours. The score bar colours
   are a data scale, so they sit outside the six, as the state colours do.
2. Light as the demo default, with dark available and measured.
3. Running shown in Graphite rather than a colour.
4. The overview led by "jobs waiting" rather than by my runs.
5. IBM Plex Sans and Mono, self-hosted.
