# Duration and speech budget

## Why it exists

A clip that tries to say more than its seconds can hold comes out rushed, with clipped
syllables, skipped beats, or a voice that runs past the picture. A clip that says
too little feels padded. Budget the spoken content against the duration before
choosing shot count, and the pacing fixes itself. This applies to human dialogue and
to animal or poem recitation and narration alike — anything with a spoken or
sung line.

## Speech budget per duration

Count only what is actually spoken aloud: CJK characters, letters, and digits. Do
not count speaker labels, punctuation, action prose, or shot notes.

| Target duration | Spoken units | Use when |
|---|---:|---|
| 10s | 20–28 | strong action, a deliberate pause, or a short scene that cannot be crossed |
| 12s | 28–36 | action and speech roughly balanced |
| 15s | 36–44 | normal dialogue, Q&A, or a recitation line-group |

- 15s holds about 40 spoken units as a working norm; 48 is the hard ceiling at a
  natural pace. At 45–48 the lines must be short and crisp and the action chain
  simple — do not also stack long pauses.
- Trim roughly 20% more when the beat carries hesitation, stutter, choking up,
  an outburst, a long silence, an embrace, or complex physical business.
- Under 24 spoken units with only simple action is an under-fill: do not assign it
  its own clip — merge it into a neighbour first (see the split rule).

## Shot density per duration — fewer, longer shots by default

| Target duration | Shots (default) | Max |
|---|---:|---:|
| 10s | 1–2 | 3 |
| 12s | 1–2 | 4 |
| 15s | 1–2 | 5 |

**Minimum-shot principle:** the default is the FEWEST shots that can hold the
content. Every extra shot multiplies the whole chain (reference frame, H3 render,
recitation, finishing) and every cross-shot seam is a place identity, style,
lighting, and voice can drift. A 15s film that fits in one continuous H3 take
should be ONE shot. Split only on a hard boundary (see below), never by habit.

**Anti-pattern — one line per shot:** do not map each poem line / each sentence /
each beat to its own clip. A 4-line poem is NOT 4 shots. That pattern turns one
global fix (title card, font, accent, watermark) into N fixes and makes the first
shot structurally different from the rest. Group lines into couplets or a single
take.

One clip carries one action chain: a start, a response, and a result. Fit one
medium action, or two small linked actions — never a wardrobe change plus a long
walk plus a prop pickup plus a long exchange in a single clip.

## Poem recitation shot plan

For a classical poem recitation film, default to **one shot per couplet** (two
lines, ~7–8s) or a **single take** for the whole short poem when it fits in 15s.
A 4-line 七言/五言绝句 → 2 couplet shots (or 1 take). The title card, the poem
columns, the unified recitation, and the watermark are applied ONCE at
master-level finishing over the joined film — so shot count is a pure creative
choice and never a fix-cost multiplier.

## One unit, one change

Each clip holds exactly:

- one scene;
- one micro-change (a discovery, a question, a denial, a decision, a touch and its
  reaction, a transfer of who is speaking, a shift in distance) — or, for a
  recitation, one line-group that lands a single image;
- one action chain;
- one clear exit.

## Fill first, then split on hard boundaries

1. Mark the boundaries that can never be merged: a scene or time-space change, a
   cast-binding change, a completed action chain, or a relationship state that has
   already turned over irreversibly.
2. Between hard boundaries, default to filling a 15s unit with continuous story —
   roughly 36–44 spoken units plus the one action chain that happens with them.
3. Split only when the merge exceeds 48 units, two independent action chains
   appear, or natural performance clearly cannot finish inside 15s. Split where a
   response completes, information lands, or an action resolves.
4. Reverse-check after splitting: any unit under 24 spoken units with only simple
   action must first be merged into the unit before or after it. Keep it as its own
   10–12s clip only when the neighbour is already near capacity, a hard boundary
   sits between them, or the beat stands on strong action, a long pause, or a
   suspense reveal.

Combine by story causality, not by line breaks, single questions, or isolated
reactions. Never cut inside an unbreakable phrase; split a long line only at a
natural clause boundary. A new scene re-establishes blocking; the next unit in the
same scene resets from the previous unit's end frame.

## Output check

Every planned shot states its duration, its spoken units, and that it carries a
single action chain with a clear exit. Flag any clip that is over budget,
under-filled, or holding two unrelated chains for human review before generation.

<!--
source: MiniMax H3 文戏 prompt template (dialogue budget + unit division),
understood and re-expressed for Director Studio. Applies to human dialogue and to
animal/poem recitation and narration. No upstream notation adopted.
-->
