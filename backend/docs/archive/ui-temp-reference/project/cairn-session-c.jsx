
// DIRECTION C: Painterly Literary
// Disco Elysium DNA. Warm ink + rust + cream on near-black.
// Wide margins, editorial type hierarchy, painterly texture.
// Feels like a literary novel designed by a art director who loves maps.
// Typeface: Cormorant Garamond display + DM Sans body.

const { useState, useEffect, useRef: useRefC } = React;

const C_TOKENS = {
  bg: "#12100e",
  bgPanel: "#16130f",
  bgWarm: "#1a1610",
  bgCard: "#1e1a13",
  border: "#2e2820",
  borderWarm: "#3a3025",
  rust: "#c4522a",
  rustDim: "#6e2e18",
  cream: "#e8dcc8",
  creamDim: "#9a8e78",
  creamFaint: "#4a4438",
  ink: "#0e0c09",
  midText: "#7a6e5a",
  dimText: "#4a4438",
  success: "#6a9e5a",
  danger: "#c04830",
  olive: "#7a8a3a",
  fog: "rgba(232,220,200,0.04)",
};

// Noise texture overlay via SVG filter
function NoiseOverlay() {
  return (
    <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none", opacity: 0.04 }}>
      <filter id="noise-c">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="4" stitchTiles="stitch" />
        <feColorMatrix type="saturate" values="0" />
      </filter>
      <rect width="100%" height="100%" filter="url(#noise-c)" />
    </svg>
  );
}

// Animated ink wash / fog
function InkWash() {
  const canvasRef = useRefC(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let w = canvas.width = canvas.offsetWidth;
    let h = canvas.height = canvas.offsetHeight;
    let t = 0;
    let raf;

    function draw() {
      ctx.clearRect(0, 0, w, h);
      // slow drifting fog patches
      for (let i = 0; i < 4; i++) {
        const x = (w * 0.2 * i + Math.sin(t * 0.0003 + i * 1.3) * w * 0.08) % w;
        const y = h * 0.5 + Math.cos(t * 0.0002 + i * 0.9) * h * 0.25;
        const r = w * 0.28;
        const grad = ctx.createRadialGradient(x, y, 0, x, y, r);
        grad.addColorStop(0, `rgba(196,82,42,0.025)`);
        grad.addColorStop(1, "transparent");
        ctx.fillStyle = grad;
        ctx.fillRect(0, 0, w, h);
      }
      t++;
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />;
}

// Hand-drawn style divider
function InkLine({ style: extraStyle }) {
  return (
    <div style={{
      height: 1,
      background: `linear-gradient(to right, transparent, ${C_TOKENS.borderWarm} 20%, ${C_TOKENS.borderWarm} 80%, transparent)`,
      margin: "12px 0",
      ...extraStyle,
    }} />
  );
}

// Small annotation-style label
function Annotation({ children, color = C_TOKENS.rust }) {
  return (
    <span style={{
      fontFamily: "'DM Sans', sans-serif",
      fontSize: 9,
      letterSpacing: 2,
      textTransform: "uppercase",
      color,
    }}>{children}</span>
  );
}

const TURNS_C = [
  { role: "dm", text: "The tavern at Grimwood Crossing reeks of pine smoke and old ale. Old Grim stands behind the bar, polishing the same tankard he's been polishing for an hour. He looks at you once — then looks away." },
  { role: "player", text: "I approach the bar and ask him quietly if he has any work that needs doing." },
  { role: "dm", text: "Grim sets the tankard down. Hard. Doesn't look up.\n\n\"Work.\" He says it like it's a confession. \"There's always work. Question is whether you'll still want it when you know what it is.\"\n\nHe reaches under the bar. Slides a folded piece of parchment across the wood." },
  { role: "check", stat: "Persuasion", dc: 14, rolled: null, modifier: 3 },
];

function DicePromptC({ check, onRoll }) {
  const [rolling, setRolling] = useState(false);
  const [face, setFace] = useState(null);
  const [result, setResult] = useState(null);

  function handleRoll() {
    setRolling(true);
    let ticks = 0;
    const interval = setInterval(() => {
      setFace(Math.floor(Math.random() * 20) + 1);
      ticks++;
      if (ticks > 14) {
        clearInterval(interval);
        const roll = Math.floor(Math.random() * 20) + 1;
        setFace(roll);
        setResult(roll);
        setRolling(false);
        setTimeout(() => onRoll(roll), 700);
      }
    }, 65);
  }

  const total = result ? result + check.modifier : null;
  const success = total >= check.dc;

  return (
    <div style={{
      margin: "16px 0",
      padding: "18px 20px",
      background: C_TOKENS.bgCard,
      borderTop: `2px solid ${C_TOKENS.rust}`,
      position: "relative",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        {/* Big d20 */}
        <div
          onClick={!rolling && !result ? handleRoll : undefined}
          style={{ cursor: result ? "default" : "pointer", flexShrink: 0, position: "relative" }}
        >
          <svg width="72" height="72" viewBox="0 0 72 72" fill="none">
            {/* Slightly imperfect polygon — hand-drawn feel */}
            <polygon
              points="36,3 70,21 70,51 36,69 2,51 2,21"
              stroke={result ? (success ? C_TOKENS.success : C_TOKENS.danger) : C_TOKENS.rust}
              strokeWidth="1.5"
              strokeLinejoin="round"
              fill={C_TOKENS.bgCard}
            />
            <polygon
              points="36,12 60,24 60,48 36,60 12,48 12,24"
              stroke={result ? (success ? C_TOKENS.success : C_TOKENS.danger) : C_TOKENS.rustDim}
              strokeWidth="0.5"
              strokeLinejoin="round"
              fill="none"
              opacity="0.4"
            />
            {/* Center number */}
            <text
              x="36" y="42"
              textAnchor="middle"
              fontFamily="'Cormorant Garamond', serif"
              fontSize={face !== null ? "26" : "14"}
              fill={result ? (success ? C_TOKENS.success : C_TOKENS.danger) : C_TOKENS.cream}
              fontWeight="300"
            >
              {face !== null ? face : "d20"}
            </text>
          </svg>
        </div>

        {/* Check info */}
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 8 }}>
            <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 22, color: C_TOKENS.cream, fontWeight: 300 }}>
              {check.stat}
            </span>
            <Annotation color={C_TOKENS.midText}>check</Annotation>
          </div>
          <div style={{ display: "flex", gap: 16, marginBottom: 10 }}>
            <div>
              <Annotation color={C_TOKENS.dimText}>Difficulty</Annotation>
              <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: C_TOKENS.creamDim }}>{check.dc}</div>
            </div>
            <div>
              <Annotation color={C_TOKENS.dimText}>Modifier</Annotation>
              <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: C_TOKENS.creamDim }}>+{check.modifier}</div>
            </div>
            {result && (
              <div>
                <Annotation color={C_TOKENS.dimText}>Result</Annotation>
                <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 18, color: success ? C_TOKENS.success : C_TOKENS.danger }}>
                  {result} + {check.modifier} = {total}
                </div>
              </div>
            )}
          </div>

          {result ? (
            <div style={{
              display: "inline-block",
              padding: "4px 12px",
              background: success ? "rgba(106,158,90,0.15)" : "rgba(192,72,48,0.15)",
              border: `1px solid ${success ? C_TOKENS.success : C_TOKENS.danger}`,
            }}>
              <Annotation color={success ? C_TOKENS.success : C_TOKENS.danger}>
                {success ? "— Success —" : "— Failure —"}
              </Annotation>
            </div>
          ) : (
            <button
              onClick={handleRoll}
              disabled={rolling}
              style={{
                background: "none",
                border: `1px solid ${C_TOKENS.rust}`,
                color: C_TOKENS.cream,
                fontFamily: "'Cormorant Garamond', serif",
                fontSize: 15,
                fontStyle: "italic",
                padding: "5px 20px",
                cursor: rolling ? "wait" : "pointer",
                opacity: rolling ? 0.6 : 1,
              }}
            >
              {rolling ? "Rolling..." : "Throw the dice"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function TurnBubbleC({ turn, onRoll }) {
  if (turn.role === "check") return <DicePromptC check={turn} onRoll={onRoll} />;

  const isDM = turn.role === "dm";

  return (
    <div style={{ marginBottom: 20, display: "flex", gap: 16 }}>
      {isDM && (
        <div style={{ flexShrink: 0, paddingTop: 3 }}>
          {/* Small cairn glyph */}
          <svg width="16" height="20" viewBox="0 0 16 20" fill="none" opacity="0.5">
            <rect x="5" y="0" width="6" height="4" rx="0.5" fill={C_TOKENS.rustDim} />
            <rect x="3" y="5" width="10" height="4" rx="0.5" fill={C_TOKENS.rustDim} />
            <rect x="1" y="10" width="14" height="4" rx="0.5" fill={C_TOKENS.rustDim} />
            <rect x="3" y="15" width="10" height="4" rx="0.5" fill={C_TOKENS.rustDim} />
          </svg>
        </div>
      )}
      <div style={{ flex: 1, textAlign: isDM ? "left" : "right" }}>
        <div style={{ marginBottom: 5 }}>
          {isDM ? (
            <Annotation color={C_TOKENS.rust}>The Dungeon Master</Annotation>
          ) : (
            <Annotation color={C_TOKENS.midText}>Ser Aldric, Fighter</Annotation>
          )}
        </div>
        <p style={{
          fontFamily: isDM ? "'Cormorant Garamond', serif" : "'DM Sans', sans-serif",
          fontSize: isDM ? 16 : 13,
          lineHeight: isDM ? 1.9 : 1.7,
          color: isDM ? C_TOKENS.cream : C_TOKENS.creamDim,
          margin: 0,
          fontStyle: isDM ? "normal" : "italic",
          fontWeight: isDM ? 300 : 400,
          whiteSpace: "pre-wrap",
          maxWidth: "90%",
          marginLeft: isDM ? 0 : "auto",
        }}>{turn.text}</p>
      </div>
    </div>
  );
}

function StatBlockC({ label, val, mod }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{
        width: 38, height: 38,
        border: `1px solid ${C_TOKENS.borderWarm}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexDirection: "column",
        background: C_TOKENS.bgCard,
      }}>
        <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 17, color: C_TOKENS.cream, fontWeight: 300, lineHeight: 1 }}>{val}</span>
        <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 7, color: C_TOKENS.midText }}>{mod >= 0 ? `+${mod}` : mod}</span>
      </div>
      <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 7, color: C_TOKENS.dimText, marginTop: 3, letterSpacing: 1, textTransform: "uppercase" }}>{label}</div>
    </div>
  );
}

export function DirectionC({ width, height }) {
  const [turns, setTurns] = useState(TURNS_C);
  const [input, setInput] = useState("");

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
    }, 1000);
  }

  return (
    <div style={{
      width, height,
      background: C_TOKENS.bg,
      display: "flex",
      overflow: "hidden",
      position: "relative",
    }}>
      <InkWash />
      <NoiseOverlay />

      {/* Left sidebar */}
      <div style={{
        width: 210,
        background: "rgba(18,16,14,0.96)",
        borderRight: `1px solid ${C_TOKENS.border}`,
        padding: "24px 18px",
        display: "flex",
        flexDirection: "column",
        flexShrink: 0,
        zIndex: 2,
      }}>
        {/* Wordmark */}
        <div style={{ marginBottom: 28 }}>
          <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 26, color: C_TOKENS.cream, fontWeight: 300, letterSpacing: 4, lineHeight: 1 }}>Cairn</div>
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 8, color: C_TOKENS.midText, letterSpacing: 3, marginTop: 3, textTransform: "uppercase" }}>AI Dungeon Master</div>
        </div>

        {/* Character portrait */}
        <div style={{
          width: "100%", aspectRatio: "3/4",
          background: C_TOKENS.bgCard,
          border: `1px solid ${C_TOKENS.borderWarm}`,
          display: "flex", alignItems: "center", justifyContent: "center",
          marginBottom: 14,
          position: "relative",
          overflow: "hidden",
        }}>
          {/* Hatching texture */}
          <svg style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.1 }}>
            <defs>
              <pattern id="hatch-c" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <line x1="0" y1="0" x2="0" y2="8" stroke={C_TOKENS.creamDim} strokeWidth="0.5" />
              </pattern>
            </defs>
            <rect width="100%" height="100%" fill="url(#hatch-c)" />
          </svg>
          <div style={{ textAlign: "center", position: "relative" }}>
            {/* Simple human silhouette */}
            <svg width="50" height="70" viewBox="0 0 50 70" fill="none" opacity="0.2">
              <ellipse cx="25" cy="14" rx="10" ry="12" fill={C_TOKENS.cream} />
              <path d="M8 70 Q8 36 25 34 Q42 36 42 70 Z" fill={C_TOKENS.cream} />
              <rect x="1" y="36" width="12" height="26" rx="5" fill={C_TOKENS.cream} />
              <rect x="37" y="36" width="12" height="26" rx="5" fill={C_TOKENS.cream} />
            </svg>
            <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 7, color: C_TOKENS.dimText, marginTop: 6, letterSpacing: 1, textTransform: "uppercase" }}>portrait</div>
          </div>
        </div>

        <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 17, color: C_TOKENS.cream, fontWeight: 400, marginBottom: 2 }}>Ser Aldric</div>
        <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 9, color: C_TOKENS.midText, letterSpacing: 2, marginBottom: 14, textTransform: "uppercase" }}>Human Fighter · Level 3</div>

        {/* HP */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <Annotation color={C_TOKENS.dimText}>Vitality</Annotation>
            <Annotation color={C_TOKENS.rust}>24 / 32</Annotation>
          </div>
          <div style={{ height: 3, background: C_TOKENS.border }}>
            <div style={{ height: "100%", width: "75%", background: C_TOKENS.rust, opacity: 0.7 }} />
          </div>
        </div>

        <InkLine />

        {/* Stats */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 8, marginBottom: 16 }}>
          {[["STR","16",3],["DEX","12",1],["CON","14",2],["INT","8",-1],["WIS","10",0],["CHA","13",1]].map(([l,v,m]) => (
            <StatBlockC key={l} label={l} val={v} mod={m} />
          ))}
        </div>

        <InkLine />

        {/* Location */}
        <div style={{ marginBottom: 16 }}>
          <Annotation color={C_TOKENS.dimText}>Location</Annotation>
          <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 14, color: C_TOKENS.creamDim, marginTop: 4, lineHeight: 1.4 }}>
            The Grimwood Tavern
          </div>
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 10, color: C_TOKENS.dimText, marginTop: 3, lineHeight: 1.5 }}>
            Crossroads inn, forest edge. Three NPCs present.
          </div>
        </div>

        <div style={{ flex: 1 }} />

        <InkLine />

        {/* Inventory */}
        <div>
          <Annotation color={C_TOKENS.dimText}>Carried</Annotation>
          <div style={{ display: "flex", flexDirection: "column", gap: 5, marginTop: 8 }}>
            {["Longsword", "Chain Mail", "Healer's Kit", "30 gold pieces"].map((item, i) => (
              <div key={i} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                <div style={{ width: 3, height: 3, borderRadius: "50%", background: C_TOKENS.rustDim, flexShrink: 0 }} />
                <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 10, color: C_TOKENS.midText }}>{item}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Main content */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", zIndex: 2 }}>
        {/* Header */}
        <div style={{
          padding: "18px 32px 14px",
          borderBottom: `1px solid ${C_TOKENS.border}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          background: "rgba(18,16,14,0.8)",
        }}>
          <div>
            <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 9, color: C_TOKENS.rust, letterSpacing: 3, textTransform: "uppercase", marginBottom: 4 }}>
              Session I · Turn 4
            </div>
            <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 22, color: C_TOKENS.cream, fontWeight: 300, letterSpacing: 1 }}>
              The Tavern at Grimwood Crossing
            </div>
          </div>
          <div style={{ display: "flex", gap: 20, alignItems: "center" }}>
            {["Lore Index", "Party", "Map"].map(l => (
              <button key={l} style={{ background: "none", border: "none", fontFamily: "'DM Sans', sans-serif", fontSize: 10, color: C_TOKENS.midText, cursor: "pointer", padding: 0, letterSpacing: 1 }}>{l}</button>
            ))}
          </div>
        </div>

        {/* Scene header */}
        <div style={{
          padding: "14px 32px 12px",
          borderBottom: `1px solid ${C_TOKENS.border}`,
        }}>
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 8, color: C_TOKENS.dimText, letterSpacing: 3, textTransform: "uppercase", marginBottom: 4 }}>
            Scene I ·  The Weary Road
          </div>
          <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 19, color: C_TOKENS.cream, fontWeight: 300, fontStyle: "italic" }}>
            The Barroom Floor
          </div>
        </div>

        {/* Transcript */}
        <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
          {turns.map((turn, i) => (
            <TurnBubbleC key={i} turn={turn} onRoll={handleRoll} />
          ))}
        </div>

        {/* Input */}
        <div style={{
          borderTop: `1px solid ${C_TOKENS.border}`,
          padding: "16px 32px",
          background: "rgba(18,16,14,0.95)",
        }}>
          {/* Quick prompts */}
          <div style={{ display: "flex", gap: 10, marginBottom: 12 }}>
            {["Ask about Kael", "Order something", "Leave quietly"].map(s => (
              <button key={s} onClick={() => setInput(s)} style={{
                background: "none",
                border: `1px solid ${C_TOKENS.border}`,
                color: C_TOKENS.midText,
                fontFamily: "'DM Sans', sans-serif",
                fontSize: 10,
                padding: "4px 12px",
                cursor: "pointer",
                letterSpacing: 0.5,
              }}>{s}</button>
            ))}
          </div>

          <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
            <div style={{ flex: 1, position: "relative" }}>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                placeholder="What do you do?"
                style={{
                  width: "100%",
                  background: C_TOKENS.bgCard,
                  border: `1px solid ${C_TOKENS.borderWarm}`,
                  borderTop: `2px solid ${C_TOKENS.rustDim}`,
                  color: C_TOKENS.cream,
                  fontFamily: "'Cormorant Garamond', serif",
                  fontSize: 15,
                  padding: "10px 14px",
                  resize: "none",
                  height: 60,
                  outline: "none",
                  fontStyle: "italic",
                  lineHeight: 1.7,
                  fontWeight: 300,
                  boxSizing: "border-box",
                }}
              />
            </div>
            <button style={{
              background: C_TOKENS.rust,
              border: "none",
              color: C_TOKENS.cream,
              fontFamily: "'DM Sans', sans-serif",
              fontSize: 10,
              letterSpacing: 2,
              padding: "0 20px",
              height: 60,
              cursor: "pointer",
              textTransform: "uppercase",
              flexShrink: 0,
            }}>
              Act
            </button>
          </div>
        </div>
      </div>

      {/* Right sidebar */}
      <div style={{
        width: 190,
        background: "rgba(18,16,14,0.96)",
        borderLeft: `1px solid ${C_TOKENS.border}`,
        padding: "24px 16px",
        flexShrink: 0,
        zIndex: 2,
        display: "flex",
        flexDirection: "column",
      }}>
        <Annotation color={C_TOKENS.dimText}>Known Facts</Annotation>
        <InkLine style={{ margin: "8px 0 12px" }} />

        {[
          { type: "Person", name: "Old Grim", note: "Retired soldier. Gruff. Measured words." },
          { type: "Person", name: "The Stranger", note: "Hooded. Has been watching since you arrived." },
          { type: "Place", name: "The Mill Road", note: "North of the village. Kael was last seen heading there." },
          { type: "Object", name: "The Parchment", note: "Grim slid it across the bar. You haven't read it yet." },
        ].map((e, i) => (
          <div key={i} style={{ marginBottom: 14 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "baseline", marginBottom: 3 }}>
              <span style={{
                fontFamily: "'DM Sans', sans-serif",
                fontSize: 7,
                color: C_TOKENS.rust,
                letterSpacing: 1,
                textTransform: "uppercase",
                flexShrink: 0,
              }}>{e.type}</span>
              <span style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 13, color: C_TOKENS.creamDim }}>{e.name}</span>
            </div>
            <p style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 10, color: C_TOKENS.midText, margin: 0, lineHeight: 1.6, paddingLeft: 10, borderLeft: `1px solid ${C_TOKENS.border}` }}>{e.note}</p>
          </div>
        ))}

        <InkLine />

        <Annotation color={C_TOKENS.dimText}>Dispositions</Annotation>
        <div style={{ marginTop: 10, display: "flex", flexDirection: "column", gap: 8 }}>
          {[
            { name: "Old Grim", mood: "Neutral", pct: 50 },
            { name: "The Stranger", mood: "Wary", pct: 25 },
            { name: "Town Guard", mood: "Suspicious", pct: 65 },
          ].map((n, i) => (
            <div key={i}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 10, color: C_TOKENS.midText }}>{n.name}</span>
                <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 9, color: C_TOKENS.creamFaint }}>{n.mood}</span>
              </div>
              <div style={{ height: 2, background: C_TOKENS.border }}>
                <div style={{ height: "100%", width: `${n.pct}%`, background: C_TOKENS.rustDim, opacity: 0.8 }} />
              </div>
            </div>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        <InkLine />

        <div>
          <Annotation color={C_TOKENS.dimText}>Active Quest</Annotation>
          <div style={{ marginTop: 8, padding: "10px 12px", background: C_TOKENS.bgCard, borderLeft: `2px solid ${C_TOKENS.rust}` }}>
            <div style={{ fontFamily: "'Cormorant Garamond', serif", fontSize: 13, color: C_TOKENS.cream, marginBottom: 3 }}>Find Kael the Merchant</div>
            <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 9, color: C_TOKENS.midText, lineHeight: 1.5 }}>Missing for three days. Owed Grim 30gp. Last seen north.</div>
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { DirectionC });
