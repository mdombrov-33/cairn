# Cairn UI reference

This directory contains planned frontend design material. The frontend does not
exist in the repository yet, so none of these artifacts proves a current HTTP
contract or implementation.

For frontend work, read in this order:

1. [../roadmap.md](../roadmap.md) for ordering, backend dependencies, and the
   Phase-A/Phase-B boundary.
2. [v4-build-brief.md](v4-build-brief.md) for the current product and visual
   specification.
3. `project/Cairn App v4.html` as the visual companion to the v4 brief.
4. Current backend routes and schemas before relying on a mockup interaction.

`v3-build-brief.md`, all earlier HTML files, the exported JSX files, and
`project/uploads/` are historical design inputs. In particular,
`project/uploads/v5.md` is an imported copy of an old design document, not the
roadmap. Do not reconstruct a frontend from those files or infer a new backend
endpoint from a visual affordance.

The v4 brief and the linked archived Slice 15/15.5 specifications control
intent. The active roadmap controls sequencing: Phase A uses the development
identity shim; authentication, billing, and the admin surface remain Phase B.
