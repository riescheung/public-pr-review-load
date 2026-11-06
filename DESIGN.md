---
name: Weave Public PR Review Load
description: Source-linked WPR and AI-estimated contribution with review coverage
colors:
  primary: "#177a6c"
  primary-deep: "#075c51"
  paper: "#f5f3ed"
  surface: "#fffefa"
  ink: "#202a28"
  muted: "#65716d"
  line: "#dce1d9"
  evidence-wash: "#e8f4ed"
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

# Design System: Weave Public PR Review Load

## Overview

**Creative North Star: "The Evidence Index"**

A working estimate, not a decorative infographic. The register-like density
lets a leader compare seven periods at a glance; source-linked details are one
click away. The interface uses restrained typographic hierarchy and rules
without ranking people by link availability.

**Key Characteristics:** compact 14-day columns, quiet warm ground, precise
data figures, and source-first explanations.

## Colors

The paper surface and deep ink keep a dense table calm. Teal identifies
WPR-bearing work and active controls. A tinted cell is not proof
of independently verified impact.

**The Evidence Rule.** WPR comes from changed files, not title or link
availability. AI estimates come only from cited model reviews, never WPR.
Pending, abstained and reserved work must not look like zero contribution.

## Typography

Newsreader carries the report title and evidence-panel subject. DM Sans is the
working interface voice. IBM Plex Mono is limited to dates, counts, estimated
WPR, mean AI tiers and review-load measurements.

## Layout

The WPR index has a rank column, contributor column, and seven equal
14-day columns. At narrower widths rank and contributor stay visible while
intervals scroll horizontally. Search, WPR/name sorting and five-person
pagination preserve the single-page report.

## Elevation & Depth

Flat ruled surfaces provide the main hierarchy. The evidence drawer alone
receives a soft offset shadow, distinguishing a temporary detail layer.

## Shapes

Small 5–11px radii belong to controls and panels.

## Components

Period cells show WPR, merged PRs and an AI-estimated mean tier with
scored/total grouped-change coverage. AI estimates open source-linked reviews.
Contributor names open a source-linked evidence drawer. Controls keep visible
hover and keyboard-focus states. Empty intervals show a dash, never a false
zero-result claim about the person's work.

## Do's and Don'ts

- **Do** keep the strongest visible source links close to every claim.
- **Do** label AI-estimated contribution separately from measured outcomes.
- **Do** expose model identity, citations and coverage beside every estimate.
- **Don't** call the provisional ranking verified user impact.
