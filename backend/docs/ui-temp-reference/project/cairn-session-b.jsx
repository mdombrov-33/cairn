
// DIRECTION B: Arcane Terminal
// Void navy + arcane cyan + cold white. Geometric, sharp.
// Feels like a magic-infused HUD — Hades meets Nier:Automata meets a spellcasting console.
// Custom icons: angular rune glyphs, scan-lines, signal noise.

const { useState, useEffect, useRef: useRefB } = React;

const B_TOKENS = {
  bg: "#050b14",
  bgPanel: "#080f1c",
  bgCard: "#0b1424",
  border: "#0e2040",
  borderCyan: "#0d4060",
  cyan: "#2ee8c8",
  cyanDim: "#0d8a70",
  cyanGlow: "rgba(46,232,200,0.15)",
  blue: "#1a6eb5",
  blueDim: "#0d3a60",
  white: "#d4eef8",
  dimText: "#2a5070",
  midText: "#4a7a9a",
  danger: "#e05050",
  warn: "#e0a030",
  success: "#2ee890",
  grid: "rgba(14,32,64,0.6)",
};

function ScanlinesBg() {
  return (
    <div style={{
      position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0,
      backgroundImage: `repeating-linear-gradient(0deg, transparent, transparent 3px, rgba(14,32,64,0.3) 3px, rgba(14,32,64,0.3) 4px)`,
      opacity: 0.5,
    }} />
  );
}

function GridBg() {
  return (
    <div style={{
      position: "absolute", inset: 0, pointerEvents: "none", zIndex: 0,
      backgroundImage: `
        linear-gradient(${B_TOKENS.grid} 1px, transparent 1px),
        linear-gradient(90deg, ${B_TOKENS.grid} 1px, transparent 1px)
      `,
      backgroundSize: "40px 40px",
    }} />
  );
}

// Animated rune glyph in background
function RuneField() {
  const canvasRef = useRefB(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    const GLYPHS = "ᚠᚢᚦᚨᚱᚲᚷᚹᚺᚾᛁᛃᛇᛈᛉᛊᛏᛒᛖᛗᛚᛜᛞᛟ⌬⌘⎔⏣◈◇⬡⬢";
    const cols = Math.floor(canvas.width / 28);
    const rows = Math.floor(canvas.height / 28);
    const cells = Array.from({ length: cols * rows }, () => ({
      glyph: GLYPHS[Math.floor(Math.random() * GLYPHS.length)],
      opacity: Math.random() * 0.04,
      tick: Math.random() * 200,
      speed: Math.random() * 0.3 + 0.05,
    }));
    let frame = 0;
    let raf;
    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      ctx.font = "14px monospace";
      cells.forEach((c, i) => {
        const col = i % cols;
        const row = Math.floor(i / cols);
        c.tick += c.speed;
        const pulse = Math.sin(c.tick * 0.05) * 0.5 + 0.5;
        const alpha = c.opacity * pulse;
        ctx.fillStyle = `rgba(46,232,200,${alpha})`;
        ctx.fillText(c.glyph, col * 28 + 8, row * 28 + 20);
        if (Math.random() < 0.0002) c.glyph = GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
      });
      frame++;
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />;
}

// Geometric icon components
function RuneIcon({ type = "cairn", size = 18, color = B_TOKENS.cyan }) {
  if (type === "cairn") return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none">
      <rect x="1" y="1" width="16" height="16" stroke={color} strokeWidth="0.5" />
      <rect x="4" y="4" width="10" height="10" stroke={color} strokeWidth="0.5" opacity="0.5" />
      <line x1="9" y1="1" x2="9" y2="17" stroke={color} strokeWidth="0.5" opacity="0.3" />
      <line x1="1" y1="9" x2="17" y2="9" stroke={color} strokeWidth="0.5" opacity="0.3" />
      <rect x="7" y="7" width="4" height="4" fill={color} opacity="0.8" />
    </svg>
  );
  if (type === "dice") return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none">
      <polygon points="9,1 17,5.5 17,12.5 9,17 1,12.5 1,5.5" stroke={color} strokeWidth="1" fill="none" />
      <circle cx="9" cy="9" r="2.5" fill={color} opacity="0.8" />
    </svg>
  );
  if (type === "npc") return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none">
      <circle cx="9" cy="7" r="3.5" stroke={color} strokeWidth="1" fill="none" />
      <path d="M2 17 Q2 11 9 11 Q16 11 16 17" stroke={color} strokeWidth="1" fill="none" />
      <circle cx="9" cy="7" r="1.5" fill={color} opacity="0.5" />
    </svg>
  );
  if (type === "lore") return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none">
      <rect x="3" y="1" width="12" height="16" stroke={color} strokeWidth="1" fill="none" />
      <line x1="6" y1="5" x2="12" y2="5" stroke={color} strokeWidth="0.8" opacity="0.7" />
      <line x1="6" y1="8" x2="12" y2="8" stroke={color} strokeWidth="0.8" opacity="0.7" />
      <line x1="6" y1="11" x2="10" y2="11" stroke={color} strokeWidth="0.8" opacity="0.7" />
      <line x1="6" y1="14" x2="8" y2="14" stroke={color} strokeWidth="0.8" opacity="0.4" />
    </svg>
  );
  return null;
}

function CyanDivider({ label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "12px 0 10px" }}>
      <div style={{ width: 6, height: 6, background: B_TOKENS.cyanDim, transform: "rotate(45deg)", flexShrink: 0 }} />
      {label && <span style={{ fontFamily: "monospace", fontSize: 9, color: B_TOKENS.dimText, letterSpacing: 3, textTransform: "uppercase" }}>{label}</span>}
      <div style={{ flex: 1, height: 1, background: B_TOKENS.border }} />
    </div>
  );
}

const TURNS_B = [
  { role: "dm", text: "The tavern at Grimwood Crossing reeks of pine smoke and old ale. Old Grim stands behind the bar, polishing the same tankard he's been polishing for an hour. He looks at you once — then looks away." },
  { role: "player", text: "I approach the bar and ask him quietly if he has any work that needs doing." },
  { role: "dm", text: "Grim sets the tankard down. Hard. Doesn't look up.\n\n\"Work.\" He says it like it's a confession. \"There's always work. Question is whether you'll still want it when you know what it is.\"\n\nHe reaches under the bar. Slides a folded piece of parchment across the wood." },
  { role: "check", stat: "PERSUASION", dc: 14, rolled: null, modifier: 3 },
];

function DicePromptB({ check, onRoll }) {
  const [rolling, setRolling] = useState(false);
  const [face, setFace] = useState(null);
  const [result, setResult] = useState(null);
  const [scanProgress, setScanProgress] = useState(0);

  function handleRoll() {
    setRolling(true);
    setScanProgress(0);
    let ticks = 0;
    const interval = setInterval(() => {
      setFace(Math.floor(Math.random() * 20) + 1);
      setScanProgress(Math.min(100, (ticks / 14) * 100));
      ticks++;
      if (ticks > 14) {
        clearInterval(interval);
        const roll = Math.floor(Math.random() * 20) + 1;
        setFace(roll);
        setResult(roll);
        setRolling(false);
        setScanProgress(100);
        setTimeout(() => onRoll(roll), 800);
      }
    }, 60);
  }

  const total = result ? result + check.modifier : null;
  const success = total >= check.dc;

  return (
    <div style={{
      background: B_TOKENS.bgCard,
      border: `1px solid ${B_TOKENS.borderCyan}`,
      padding: "16px 20px",
      position: "relative",
      marginTop: 8,
      overflow: "hidden",
    }}>
      {/* Corner marks */}
      {[[0,0],[0,1],[1,0],[1,1]].map(([r,c], i) => (
        <div key={i} style={{
          position: "absolute",
          top: r ? "auto" : 0, bottom: r ? 0 : "auto",
          left: c ? "auto" : 0, right: c ? 0 : "auto",
          width: 8, height: 8,
          borderTop: r ? "none" : `1px solid ${B_TOKENS.cyan}`,
          borderBottom: r ? `1px solid ${B_TOKENS.cyan}` : "none",
          borderLeft: c ? "none" : `1px solid ${B_TOKENS.cyan}`,
          borderRight: c ? `1px solid ${B_TOKENS.cyan}` : "none",
        }} />
      ))}

      {/* Scan line */}
      {rolling && (
        <div style={{
          position: "absolute", left: 0, right: 0, height: 1,
          background: B_TOKENS.cyan,
          top: `${scanProgress}%`,
          boxShadow: `0 0 8px ${B_TOKENS.cyan}`,
          transition: "top 0.05s linear",
        }} />
      )}

      <div style={{ display: "flex", alignItems: "center", gap: 24 }}>
        <div>
          <div style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText, letterSpacing: 3, marginBottom: 8 }}>// SKILL_CHECK</div>
          <div style={{ fontFamily: "monospace", fontSize: 13, color: B_TOKENS.white, marginBottom: 4 }}>{check.stat}</div>
          <div style={{ fontFamily: "monospace", fontSize: 10, color: B_TOKENS.midText }}>DC:{check.dc} · MOD:+{check.modifier}</div>
        </div>

        <div style={{ flex: 1, display: "flex", justifyContent: "center" }}>
          <div
            onClick={!rolling && !result ? handleRoll : undefined}
            style={{
              width: 56, height: 56,
              cursor: result ? "default" : "pointer",
              display: "flex", alignItems: "center", justifyContent: "center",
              position: "relative",
            }}
          >
            <svg width="56" height="56" viewBox="0 0 56 56" style={{ position: "absolute" }}>
              <polygon points="28,2 54,16 54,40 28,54 2,40 2,16"
                stroke={result ? (success ? B_TOKENS.success : B_TOKENS.danger) : B_TOKENS.cyan}
                strokeWidth="1"
                fill={B_TOKENS.bgCard}
                style={{ filter: result ? `drop-shadow(0 0 6px ${success ? B_TOKENS.success : B_TOKENS.danger})` : `drop-shadow(0 0 6px ${B_TOKENS.cyanDim})` }}
              />
              <polygon points="28,8 48,19 48,37 28,48 8,37 8,19"
                stroke={result ? (success ? B_TOKENS.success : B_TOKENS.danger) : B_TOKENS.borderCyan}
                strokeWidth="0.5" fill="none" opacity="0.5"
              />
            </svg>
            <span style={{
              fontFamily: "monospace",
              fontSize: face !== null ? 20 : 11,
              color: result ? (success ? B_TOKENS.success : B_TOKENS.danger) : B_TOKENS.cyan,
              position: "relative", zIndex: 1,
              textShadow: `0 0 10px currentColor`,
            }}>
              {face !== null ? face : "d20"}
            </span>
          </div>
        </div>

        <div style={{ textAlign: "right" }}>
          {result ? (
            <>
              <div style={{ fontFamily: "monospace", fontSize: 18, color: success ? B_TOKENS.success : B_TOKENS.danger, textShadow: `0 0 12px currentColor` }}>
                {total}
              </div>
              <div style={{ fontFamily: "monospace", fontSize: 9, color: success ? B_TOKENS.success : B_TOKENS.danger, letterSpacing: 2 }}>
                {success ? "// PASS" : "// FAIL"}
              </div>
            </>
          ) : (
            <button
              onClick={handleRoll}
              disabled={rolling}
              style={{
                background: "none",
                border: `1px solid ${B_TOKENS.cyan}`,
                color: B_TOKENS.cyan,
                fontFamily: "monospace",
                fontSize: 10,
                letterSpacing: 2,
                padding: "6px 14px",
                cursor: rolling ? "wait" : "pointer",
                opacity: rolling ? 0.5 : 1,
                textShadow: `0 0 8px ${B_TOKENS.cyan}`,
              }}
            >
              {rolling ? "..." : "ROLL"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function TurnBubbleB({ turn, onRoll }) {
  if (turn.role === "check") return (
    <div style={{ paddingLeft: 20 }}>
      <DicePromptB check={turn} onRoll={onRoll} />
    </div>
  );

  const isDM = turn.role === "dm";
  return (
    <div style={{ marginBottom: 14 }}>
      {isDM ? (
        <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
          <RuneIcon type="cairn" size={12} />
          <span style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.cyanDim, letterSpacing: 3 }}>DM_AGENT</span>
        </div>
      ) : (
        <div style={{ textAlign: "right", marginBottom: 4 }}>
          <span style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText, letterSpacing: 3 }}>PLAYER::SER_ALDRIC</span>
        </div>
      )}
      <div style={{
        background: isDM ? B_TOKENS.bgCard : "transparent",
        border: isDM ? `1px solid ${B_TOKENS.border}` : "none",
        borderLeft: isDM ? `2px solid ${B_TOKENS.cyanDim}` : "none",
        borderRight: !isDM ? `1px solid ${B_TOKENS.border}` : "none",
        padding: isDM ? "10px 14px" : "6px 14px",
        textAlign: isDM ? "left" : "right",
        position: "relative",
      }}>
        {isDM && <div style={{ position: "absolute", top: 0, right: 0, width: 4, height: 4, background: B_TOKENS.cyanDim }} />}
        <p style={{
          fontFamily: isDM ? "'Space Mono', monospace" : "monospace",
          fontSize: 12,
          lineHeight: 1.8,
          color: isDM ? B_TOKENS.white : B_TOKENS.midText,
          margin: 0,
          whiteSpace: "pre-wrap",
        }}>{turn.text}</p>
      </div>
    </div>
  );
}

function StatBarB({ label, val, max = 20, color = B_TOKENS.cyan }) {
  const pct = (val / max) * 100;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
        <span style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText, letterSpacing: 1 }}>{label}</span>
        <span style={{ fontFamily: "monospace", fontSize: 8, color }}>{val}</span>
      </div>
      <div style={{ height: 2, background: B_TOKENS.border, position: "relative" }}>
        <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: `${pct}%`, background: color, boxShadow: `0 0 6px ${color}` }} />
      </div>
    </div>
  );
}

export function DirectionB({ width, height }) {
  const [turns, setTurns] = useState(TURNS_B);
  const [input, setInput] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  function handleRoll(roll) {
    const total = roll + 3;
    const success = total >= 14;
    setTurns(prev => prev.map(t => t.role === "check" ? { ...t, rolled: roll } : t));
    setTimeout(() => {
      setTurns(prev => [...prev, {
        role: "dm",
        text: success
          ? "Grim meets your eyes for the first time. Something shifts in the hard lines of his face.\n\n\"Alright. There's a merchant. Kael. Came through here three nights past. Owes me thirty gold and a lot more than that in explanations. He headed north — toward the old mill road.\"\n\nHe picks up the tankard again. \"Don't come back without word of him.\""
          : "Grim doesn't even look up. \"I don't talk business with strangers.\" He turns away, and that's the end of it — for now.",
      }]);
    }, 1200);
  }

  const timeStr = `${String(Math.floor((tick % 3600) / 60)).padStart(2,"0")}:${String(tick % 60).padStart(2,"0")}`;

  return (
    <div style={{
      width, height,
      background: B_TOKENS.bg,
      display: "flex",
      overflow: "hidden",
      position: "relative",
      fontFamily: "monospace",
    }}>
      <GridBg />
      <ScanlinesBg />
      <RuneField />

      {/* Left sidebar */}
      <div style={{
        width: 190,
        background: "rgba(5,11,20,0.92)",
        borderRight: `1px solid ${B_TOKENS.border}`,
        padding: "16px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 0,
        flexShrink: 0,
        zIndex: 2,
        backdropFilter: "blur(4px)",
      }}>
        {/* Logo */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 20 }}>
          <RuneIcon type="cairn" size={20} />
          <div>
            <div style={{ fontFamily: "monospace", fontSize: 13, color: B_TOKENS.cyan, letterSpacing: 4, textShadow: `0 0 10px ${B_TOKENS.cyan}` }}>CAIRN</div>
            <div style={{ fontFamily: "monospace", fontSize: 7, color: B_TOKENS.dimText, letterSpacing: 2 }}>v1.0.0 · LOCAL</div>
          </div>
        </div>

        <CyanDivider label="Character" />

        {/* Character portrait placeholder */}
        <div style={{
          width: "100%", aspectRatio: "1/1",
          border: `1px solid ${B_TOKENS.borderCyan}`,
          background: B_TOKENS.bgCard,
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 10,
          position: "relative",
          overflow: "hidden",
        }}>
          <div style={{
            position: "absolute", inset: 0,
            backgroundImage: `repeating-linear-gradient(45deg, transparent, transparent 4px, rgba(14,32,64,0.3) 4px, rgba(14,32,64,0.3) 5px)`,
          }} />
          <div style={{ position: "relative", textAlign: "center" }}>
            <RuneIcon type="npc" size={36} color={B_TOKENS.borderCyan} />
            <div style={{ fontFamily: "monospace", fontSize: 7, color: B_TOKENS.dimText, letterSpacing: 1, marginTop: 4 }}>portrait</div>
          </div>
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: B_TOKENS.borderCyan, boxShadow: `0 0 8px ${B_TOKENS.cyanDim}` }} />
        </div>

        <div style={{ fontFamily: "monospace", fontSize: 11, color: B_TOKENS.white, letterSpacing: 2, marginBottom: 2 }}>SER_ALDRIC</div>
        <div style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText, letterSpacing: 1, marginBottom: 12 }}>FIGHTER · LVL:3 · HP:24/32</div>

        <StatBarB label="HP" val={24} max={32} color={B_TOKENS.success} />
        <StatBarB label="STR" val={16} max={20} />
        <StatBarB label="DEX" val={12} max={20} color={B_TOKENS.blue} />
        <StatBarB label="CHA" val={13} max={20} color="#b060e0" />

        <CyanDivider label="Location" />

        <div style={{ fontFamily: "monospace", fontSize: 9, color: B_TOKENS.midText, lineHeight: 1.6 }}>
          <span style={{ color: B_TOKENS.cyanDim }}>›</span> Grimwood Tavern<br />
          <span style={{ color: B_TOKENS.dimText, fontSize: 8 }}>session:1 · turn:4</span>
        </div>

        <div style={{ flex: 1 }} />

        <CyanDivider label="Nav" />
        {["/ campaign", "/ character", "/ lore", "/ settings"].map((item, i) => (
          <div key={i} style={{ fontFamily: "monospace", fontSize: 9, color: i === 0 ? B_TOKENS.cyan : B_TOKENS.dimText, padding: "4px 0", cursor: "pointer", letterSpacing: 1 }}>
            {item}
          </div>
        ))}
      </div>

      {/* Main area */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", zIndex: 2 }}>
        {/* Header bar */}
        <div style={{
          borderBottom: `1px solid ${B_TOKENS.border}`,
          padding: "8px 16px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: "rgba(5,11,20,0.9)",
          backdropFilter: "blur(4px)",
        }}>
          <div style={{ fontFamily: "monospace", fontSize: 10, color: B_TOKENS.midText, letterSpacing: 2 }}>
            <span style={{ color: B_TOKENS.cyanDim }}>›</span> THE_TAVERN_AT_GRIMWOOD · SESSION_01
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            <span style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText }}>
              {timeStr} · <span style={{ color: B_TOKENS.success }}>●</span> CONNECTED
            </span>
            <span style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText }}>SSE:ACTIVE</span>
          </div>
        </div>

        {/* Scene label */}
        <div style={{
          padding: "10px 16px 8px",
          borderBottom: `1px solid ${B_TOKENS.border}`,
          background: "rgba(8,15,28,0.8)",
          display: "flex",
          alignItems: "center",
          gap: 12,
        }}>
          <div style={{ width: 3, height: 20, background: B_TOKENS.cyan, boxShadow: `0 0 8px ${B_TOKENS.cyan}` }} />
          <div>
            <div style={{ fontFamily: "monospace", fontSize: 14, color: B_TOKENS.white, letterSpacing: 2 }}>THE BARROOM FLOOR</div>
            <div style={{ fontFamily: "monospace", fontSize: 8, color: B_TOKENS.dimText, letterSpacing: 1 }}>SCENE_01 · 3 NPCs present · Neutral atmosphere</div>
          </div>
        </div>

        {/* Transcript */}
        <div style={{ flex: 1, overflowY: "auto", padding: "16px", display: "flex", flexDirection: "column", gap: 2 }}>
          {turns.map((turn, i) => (
            <TurnBubbleB key={i} turn={turn} onRoll={handleRoll} />
          ))}
        </div>

        {/* Input */}
        <div style={{
          borderTop: `1px solid ${B_TOKENS.border}`,
          padding: "10px 14px",
          background: "rgba(5,11,20,0.95)",
          backdropFilter: "blur(4px)",
        }}>
          <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
            {["→ ask about kael", "→ buy drink", "→ leave"].map(s => (
              <button key={s} onClick={() => setInput(s.replace("→ ", ""))} style={{
                background: "none",
                border: `1px solid ${B_TOKENS.border}`,
                color: B_TOKENS.dimText,
                fontFamily: "monospace",
                fontSize: 9,
                padding: "3px 10px",
                cursor: "pointer",
                letterSpacing: 1,
              }}>{s}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
            <div style={{ fontFamily: "monospace", fontSize: 12, color: B_TOKENS.cyanDim, alignSelf: "center", flexShrink: 0 }}>›</div>
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="describe your action..."
              style={{
                flex: 1,
                background: "none",
                border: "none",
                borderBottom: `1px solid ${B_TOKENS.borderCyan}`,
                color: B_TOKENS.white,
                fontFamily: "monospace",
                fontSize: 12,
                padding: "6px 0",
                outline: "none",
                letterSpacing: 1,
              }}
            />
            <button style={{
              background: "none",
              border: `1px solid ${B_TOKENS.cyan}`,
              color: B_TOKENS.cyan,
              fontFamily: "monospace",
              fontSize: 9,
              letterSpacing: 3,
              padding: "0 14px",
              cursor: "pointer",
              textShadow: `0 0 8px ${B_TOKENS.cyan}`,
            }}>SEND</button>
          </div>
        </div>
      </div>

      {/* Right panel */}
      <div style={{
        width: 180,
        background: "rgba(5,11,20,0.92)",
        borderLeft: `1px solid ${B_TOKENS.border}`,
        padding: "16px 12px",
        flexShrink: 0,
        zIndex: 2,
        backdropFilter: "blur(4px)",
        display: "flex",
        flexDirection: "column",
      }}>
        <CyanDivider label="NPC Status" />
        {[
          { name: "OLD_GRIM", state: "NEUTRAL", icon: "npc", bar: 50 },
          { name: "STRANGER", state: "WATCHING", icon: "npc", bar: 20 },
          { name: "TOWN_GUARD", state: "HOSTILE", icon: "npc", bar: 80 },
        ].map((n, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
              <RuneIcon type="npc" size={11} color={B_TOKENS.dimText} />
              <span style={{ fontFamily: "monospace", fontSize: 9, color: B_TOKENS.midText }}>{n.name}</span>
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
              <span style={{ fontFamily: "monospace", fontSize: 7, color: B_TOKENS.dimText }}>disposition</span>
              <span style={{ fontFamily: "monospace", fontSize: 7, color: n.state === "HOSTILE" ? B_TOKENS.danger : n.state === "WATCHING" ? B_TOKENS.warn : B_TOKENS.midText }}>{n.state}</span>
            </div>
            <div style={{ height: 2, background: B_TOKENS.border }}>
              <div style={{ height: "100%", width: `${n.bar}%`, background: n.state === "HOSTILE" ? B_TOKENS.danger : n.state === "WATCHING" ? B_TOKENS.warn : B_TOKENS.cyanDim }} />
            </div>
          </div>
        ))}

        <CyanDivider label="World Log" />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {[
            { tag: "NPC", msg: "Kael: merchant, headed north" },
            { tag: "DEBT", msg: "Grim owed 30gp by Kael" },
            { tag: "QUEST", msg: "Find Kael · active" },
          ].map((e, i) => (
            <div key={i} style={{ borderLeft: `1px solid ${B_TOKENS.borderCyan}`, paddingLeft: 8 }}>
              <span style={{ fontFamily: "monospace", fontSize: 7, color: B_TOKENS.cyanDim, letterSpacing: 1 }}>[{e.tag}]</span>
              <div style={{ fontFamily: "monospace", fontSize: 9, color: B_TOKENS.dimText, lineHeight: 1.5 }}>{e.msg}</div>
            </div>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        <CyanDivider label="Agents" />
        {[
          { name: "scene_narrator", status: "idle" },
          { name: "rules_lawyer", status: "active" },
          { name: "lore_keeper", status: "idle" },
          { name: "npc::old_grim", status: "standby" },
        ].map((a, i) => (
          <div key={i} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 5 }}>
            <div style={{
              width: 5, height: 5, borderRadius: "50%",
              background: a.status === "active" ? B_TOKENS.success : a.status === "standby" ? B_TOKENS.warn : B_TOKENS.dimText,
              flexShrink: 0,
              boxShadow: a.status === "active" ? `0 0 6px ${B_TOKENS.success}` : "none",
            }} />
            <span style={{ fontFamily: "monospace", fontSize: 8, color: a.status === "active" ? B_TOKENS.midText : B_TOKENS.dimText }}>{a.name}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { DirectionB });
