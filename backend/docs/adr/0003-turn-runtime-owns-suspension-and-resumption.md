# Turn runtime owns suspension and resumption

Foreground HTTP turn handling crosses one turn-runtime interface for preparation, continuation, and
resumption. The runtime owns tagged internal suspension outcomes and adapts them to the existing
`Turn.check_data`, checkpoint, HTTP, and SSE representations, keeping routes and graph topology from
learning pause-specific workflow details while preserving client and persistence compatibility.
