---
name: Weave Engineering Impact
description: An evidence-led leaderboard for public engineering outcomes
colors:
  primary: "#177a6c"
  primary-deep: "#075c51"
  paper: "#f5f3ed"
  surface: "#fffefa"
  ink: "#202a28"
  muted: "#65716d"
  line: "#dce1d9"
  evidence-wash: "#e8f4ed"
  attention: "#a75b21"
typography:
  display:
    fontFamily: "Newsreader, Georgia, serif"
    fontSize: "37px"
    fontWeight: 500
    lineHeight: 1.05
  body:
    fontFamily: "DM Sans, sans-serif"
    fontSize: "13px"
    fontWeight: 400
    lineHeight: 1.45
  data:
    fontFamily: "IBM Plex Mono, monospace"
    fontSize: "12px"
    fontWeight: 500
    lineHeight: 1.3
rounded:
  control: "6px"
  panel: "11px"
spacing:
  compact: "8px"
  standard: "16px"
  section: "27px"
components:
  period-cell:
    backgroundColor: "{colors.evidence-wash}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "7px 10px"
---

# Design System: Weave Engineering Impact

## Overview

**Creative North Star: "The Evidence Index"**

A working leaderboard, not a decorative infographic. The register-like density
lets a leader compare seven periods at a glance; source-linked details are one
click away. The interface uses restrained typographic hierarchy and rules,
while a single small rank insignia gives the top five an unmistakable place.

**Key Characteristics:** compact 14-day columns, quiet warm ground, precise
data figures, source-first explanations, and a non-accusatory attention mark.

## Colors

The paper surface and deep ink keep a dense table calm. Teal identifies
supported evidence and active controls; amber appears only on the investigation
symbol. A tinted evidence cell is a status cue, not a claim of verified impact.

**The Evidence Rule.** Reserve teal fills for supported outcomes; never use
amber as a negative performance grade.

## Typography

Newsreader carries the report title and evidence-panel subject. DM Sans is the
working interface voice. IBM Plex Mono is limited to dates, point values,
rank figures, and review-load measurements.

## Layout

The leaderboard has a separate rank column, a contributor column, and seven
equal 14-day columns. At narrower widths the rank and contributor columns stay
visible while the interval grid scrolls horizontally. Search, sort, filter,
and five-person pagination preserve the single-page report.

## Elevation & Depth

Flat ruled surfaces provide the main hierarchy. The evidence drawer alone
receives a soft offset shadow, distinguishing a temporary detail layer.

## Shapes

Small 5–11px radii belong to controls and panels. A custom vector seal marks
ranks 1–5; the amber diamond is a separate investigation mark.

## Components

Period cells show evidence points, qualifying outcomes, and WPR in that order.
Contributor names open a source-linked evidence drawer. Controls keep visible
hover and keyboard-focus states. Empty intervals show a dash, never a false
zero-result claim about the person's work.

## Do's and Don'ts

- **Do** keep the strongest visible source links close to every claim.
- **Do** show unscored contributions without equating them to no impact.
- **Don't** use review load in the impact score.
- **Don't** present the attention mark as an employee-performance verdict.
