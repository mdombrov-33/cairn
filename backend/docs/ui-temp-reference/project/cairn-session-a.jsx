
// DIRECTION A: Dark Grimoire
// Ink + aged gold + ember. Cinzel display, IM Fell body.
// Feels like reading a haunted tome. Candlelit. Parchment dust particles.
// Closest ref: BG3 inventory screen + old Diablo 2 UI — ornate, heavy, readable.

const { useState, useEffect, useRef } = React;

const A_TOKENS = {
  bg: "#0d0b0f",
  bgPanel: "#13100f",
  bgDeep: "#0a0809",
  border: "#2e2318",
  borderGold: "#4a3820",
  gold: "#c9a84c",
  goldDim: "#7a6030",
  ember: "#b54a1e",
  parchment: "#e8d9b8",
  parchmentDim: "#9a8f78",
  ink: "#1e1812",
  white: "#f0e8d8",
  dimText: "#7a7060",
  success: "#5a9e5a",
  danger: "#c04030",
};

// Floating dust particles
function ParchmentDust() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    canvas.width = canvas.offsetWidth;
    canvas.height = canvas.offsetHeight;
    const particles = Array.from({ length: 60 }, () => ({
      x: Math.random() * canvas.width,
      y: Math.random() * canvas.height,
      r: Math.random() * 1.5 + 0.3,
      dx: (Math.random() - 0.5) * 0.12,
      dy: -Math.random() * 0.2 - 0.05,
      opacity: Math.random() * 0.25 + 0.05,
    }));
    let raf;
    function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      particles.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(201,168,76,${p.opacity})`;
        ctx.fill();
        p.x += p.dx;
        p.y += p.dy;
        if (p.y < -2) { p.y = canvas.height + 2; p.x = Math.random() * canvas.width; }
        if (p.x < -2) p.x = canvas.width + 2;
        if (p.x > canvas.width + 2) p.x = -2;
      });
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, []);
  return <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />;
}

// Runic corner ornament
function CornerRune({ size = 20, color = A_TOKENS.goldDim }) {
  return (
    <svg width={size} height={size} viewBox="0 0 20 20" fill="none">
      <path d="M0 0 L8 0 L8 2 L2 2 L2 8 L0 8 Z" fill={color} />
      <path d="M4 4 L6 4 L6 6 L4 6 Z" fill={color} opacity="0.5" />
    </svg>
  );
}

function OrnamentDivider() {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "10px 0" }}>
      <div style={{ flex: 1, height: 1, background: `linear-gradient(to right, transparent, ${A_TOKENS.borderGold})` }} />
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <rect x="4" y="0" width="4" height="4" transform="rotate(45 6 2)" fill={A_TOKENS.goldDim} />
        <rect x="4" y="8" width="4" height="4" transform="rotate(45 6 10)" fill={A_TOKENS.goldDim} opacity="0.4" />
      </svg>
      <div style={{ flex: 1, height: 1, background: `linear-gradient(to left, transparent, ${A_TOKENS.borderGold})` }} />
    </div>
  );
}

const TURNS_A = [
  { role: "dm", text: "The tavern at Grimwood Crossing reeks of pine smoke and old ale. Old Grim stands behind the bar, polishing the same tankard he's been polishing for an hour. He looks at you once — then looks away." },
  { role: "player", text: "I approach the bar and ask him quietly if he has any work that needs doing." },
  { role: "dm", text: "Grim sets the tankard down. Hard. Doesn't look up.\n\n\"Work.\" He says it like it's a confession. \"There's always work. Question is whether you'll still want it when you know what it is.\"\n\nHe reaches under the bar. Slides a folded piece of parchment across the wood." },
  { role: "check", stat: "PERSUASION", dc: 14, rolled: null, modifier: 3 },
];

function DicePrompt({ check, onRoll }) {
  const [rolling, setRolling] = useState(false);
  const [face, setFace] = useState(20);
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
        setTimeout(() => onRoll(roll), 600);
      }
    }, 60);
  }

  const total = result ? result + check.modifier : null;
  const success = total >= check.dc;

  return (
    <div style={{
      background: A_TOKENS.bgDeep,
      border: `1px solid ${A_TOKENS.borderGold}`,
      padding: "18px 20px",
      position: "relative",
      marginTop: 8,
    }}>
      <div style={{ position: "absolute", top: 0, left: 0 }}><CornerRune /></div>
      <div style={{ position: "absolute", top: 0, right: 0, transform: "scaleX(-1)" }}><CornerRune /></div>
      <div style={{ position: "absolute", bottom: 0, left: 0, transform: "scaleY(-1)" }}><CornerRune /></div>
      <div style={{ position: "absolute", bottom: 0, right: 0, transform: "scale(-1)" }}><CornerRune /></div>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: "'Cinzel', serif", color: A_TOKENS.gold, fontSize: 11, letterSpacing: 3, marginBottom: 12, textTransform: "uppercase" }}>
          Skill Check Required
        </div>
        <div style={{ fontFamily: "'Cinzel', serif", color: A_TOKENS.parchment, fontSize: 16, marginBottom: 4 }}>
          {check.stat}
        </div>
        <div style={{ color: A_TOKENS.parchmentDim, fontSize: 12, marginBottom: 16 }}>
          DC {check.dc} · Modifier +{check.modifier}
        </div>
        <div
          onClick={!rolling && !result ? handleRoll : undefined}
          style={{
            width: 64, height: 64,
            margin: "0 auto 14px",
            cursor: result ? "default" : "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            position: "relative",
          }}
        >
          <svg width="64" height="64" viewBox="0 0 64 64" fill="none" style={{ position: "absolute" }}>
            <polygon points="32,4 60,20 60,44 32,60 4,44 4,20" stroke={result ? (success ? A_TOKENS.success : A_TOKENS.danger) : A_TOKENS.gold} strokeWidth="1.5" fill={A_TOKENS.bgDeep} />
            <polygon points="32,10 54,23 54,41 32,54 10,41 10,23" stroke={result ? (success ? A_TOKENS.success : A_TOKENS.danger) : A_TOKENS.borderGold} strokeWidth="0.5" fill="none" />
          </svg>
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: result ? 22 : 18, color: result ? (success ? A_TOKENS.success : A_TOKENS.danger) : A_TOKENS.gold, position: "relative", zIndex: 1, transition: "all 0.1s" }}>
            {rolling ? face : result ? face : "d20"}
          </span>
        </div>
        {result && (
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 13, color: success ? A_TOKENS.success : A_TOKENS.danger, letterSpacing: 2 }}>
            {result} + {check.modifier} = {total} · {success ? "SUCCESS" : "FAILURE"}
          </div>
        )}
        {!result && (
          <button
            onClick={handleRoll}
            disabled={rolling}
            style={{
              background: "none",
              border: `1px solid ${A_TOKENS.gold}`,
              color: A_TOKENS.gold,
              fontFamily: "'Cinzel', serif",
              fontSize: 11,
              letterSpacing: 3,
              padding: "8px 24px",
              cursor: rolling ? "wait" : "pointer",
              textTransform: "uppercase",
              opacity: rolling ? 0.5 : 1,
            }}
          >
            {rolling ? "Rolling..." : "Roll the Dice"}
          </button>
        )}
      </div>
    </div>
  );
}

function TurnBubble({ turn, onRoll }) {
  if (turn.role === "check") {
    return (
      <div style={{ paddingLeft: 24 }}>
        <DicePrompt check={turn} onRoll={onRoll} />
      </div>
    );
  }
  const isDM = turn.role === "dm";
  return (
    <div style={{ marginBottom: 16 }}>
      {isDM && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <polygon points="7,1 13,4 13,10 7,13 1,10 1,4" fill={A_TOKENS.borderGold} stroke={A_TOKENS.gold} strokeWidth="0.5" />
            <polygon points="7,3.5 11,5.5 11,8.5 7,10.5 3,8.5 3,5.5" fill={A_TOKENS.goldDim} opacity="0.4" />
          </svg>
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.goldDim, letterSpacing: 3, textTransform: "uppercase" }}>Dungeon Master</span>
        </div>
      )}
      {!isDM && (
        <div style={{ textAlign: "right", marginBottom: 6 }}>
          <span style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText, letterSpacing: 3, textTransform: "uppercase" }}>Ser Aldric · Fighter</span>
        </div>
      )}
      <div style={{
        background: isDM ? A_TOKENS.bgPanel : "transparent",
        border: isDM ? `1px solid ${A_TOKENS.border}` : "none",
        borderLeft: isDM ? `2px solid ${A_TOKENS.borderGold}` : "none",
        borderRight: !isDM ? `2px solid ${A_TOKENS.borderGold}` : "none",
        padding: isDM ? "12px 16px" : "0 0 0 0",
        textAlign: isDM ? "left" : "right",
      }}>
        <p style={{
          fontFamily: "'IM Fell English', serif",
          fontSize: 14,
          lineHeight: 1.75,
          color: isDM ? A_TOKENS.parchment : A_TOKENS.parchmentDim,
          margin: 0,
          fontStyle: isDM ? "normal" : "italic",
          whiteSpace: "pre-wrap",
        }}>{turn.text}</p>
      </div>
    </div>
  );
}

function StatPip({ label, val, mod }) {
  return (
    <div style={{ textAlign: "center" }}>
      <div style={{
        width: 40, height: 46,
        border: `1px solid ${A_TOKENS.borderGold}`,
        background: A_TOKENS.bgDeep,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        position: "relative",
        clipPath: "polygon(0 8px, 8px 0, calc(100% - 8px) 0, 100% 8px, 100% calc(100% - 8px), calc(100% - 8px) 100%, 8px 100%, 0 calc(100% - 8px))",
      }}>
        <span style={{ fontFamily: "'Cinzel', serif", fontSize: 16, color: A_TOKENS.gold }}>{val}</span>
        <span style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText }}>{mod >= 0 ? `+${mod}` : mod}</span>
      </div>
      <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.dimText, marginTop: 4, letterSpacing: 1 }}>{label}</div>
    </div>
  );
}

export function DirectionA({ width, height }) {
  const [turns, setTurns] = useState(TURNS_A);
  const [input, setInput] = useState("");
  const scrollRef = useRef(null);

  function handleRoll(roll) {
    const total = roll + 3;
    const success = total >= 14;
    setTurns(prev => {
      const next = [...prev];
      const idx = next.findIndex(t => t.role === "check");
      if (idx !== -1) next[idx] = { ...next[idx], rolled: roll };
      return next;
    });
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
      background: A_TOKENS.bg,
      display: "flex",
      overflow: "hidden",
      position: "relative",
      fontFamily: "'IM Fell English', serif",
    }}>
      <ParchmentDust />

      {/* Left sidebar — character sheet */}
      <div style={{
        width: 200,
        background: A_TOKENS.bgDeep,
        borderRight: `1px solid ${A_TOKENS.border}`,
        display: "flex",
        flexDirection: "column",
        padding: "20px 14px",
        gap: 0,
        flexShrink: 0,
        zIndex: 1,
      }}>
        {/* Character portrait placeholder */}
        <div style={{
          width: "100%",
          aspectRatio: "1/1",
          border: `1px solid ${A_TOKENS.borderGold}`,
          background: A_TOKENS.ink,
          position: "relative",
          marginBottom: 10,
          display: "flex", alignItems: "center", justifyContent: "center",
          overflow: "hidden",
        }}>
          <div style={{ position: "absolute", top: 2, left: 2 }}><CornerRune size={14} /></div>
          <div style={{ position: "absolute", top: 2, right: 2, transform: "scaleX(-1)" }}><CornerRune size={14} /></div>
          <div style={{ position: "absolute", bottom: 2, left: 2, transform: "scaleY(-1)" }}><CornerRune size={14} /></div>
          <div style={{ position: "absolute", bottom: 2, right: 2, transform: "scale(-1)" }}><CornerRune size={14} /></div>
          {/* Silhouette placeholder */}
          <svg width="60" height="80" viewBox="0 0 60 80" fill="none" opacity="0.15">
            <ellipse cx="30" cy="18" rx="13" ry="15" fill={A_TOKENS.parchment} />
            <path d="M10 80 Q10 45 30 42 Q50 45 50 80 Z" fill={A_TOKENS.parchment} />
            <rect x="2" y="44" width="14" height="28" rx="4" fill={A_TOKENS.parchment} />
            <rect x="44" y="44" width="14" height="28" rx="4" fill={A_TOKENS.parchment} />
          </svg>
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, background: "rgba(0,0,0,0.6)", padding: "3px 0", textAlign: "center" }}>
            <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.parchmentDim, letterSpacing: 1 }}>character portrait</span>
          </div>
        </div>

        <div style={{ fontFamily: "'Cinzel', serif", fontSize: 13, color: A_TOKENS.gold, textAlign: "center", marginBottom: 2 }}>Ser Aldric</div>
        <div style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText, textAlign: "center", letterSpacing: 2, marginBottom: 14 }}>HUMAN FIGHTER · LVL 3</div>

        {/* HP bar */}
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.dimText, letterSpacing: 1 }}>VITALITY</span>
            <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.ember }}>24 / 32</span>
          </div>
          <div style={{ height: 4, background: A_TOKENS.border, position: "relative" }}>
            <div style={{ position: "absolute", left: 0, top: 0, height: "100%", width: "75%", background: `linear-gradient(to right, ${A_TOKENS.ember}, ${A_TOKENS.gold})` }} />
          </div>
        </div>

        <OrnamentDivider />

        {/* Stats grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 6, marginBottom: 14 }}>
          {[["STR","16","+3"],["DEX","12","+1"],["CON","14","+2"],["INT","8","-1"],["WIS","10","0"],["CHA","13","+1"]].map(([l,v,m]) => (
            <StatPip key={l} label={l} val={v} mod={parseInt(m)} />
          ))}
        </div>

        <OrnamentDivider />

        {/* Location */}
        <div style={{ marginTop: 4 }}>
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.dimText, letterSpacing: 2, marginBottom: 6 }}>LOCATION</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
              <rect x="1" y="1" width="8" height="8" stroke={A_TOKENS.borderGold} strokeWidth="0.5" fill={A_TOKENS.bgDeep} />
              <rect x="3" y="3" width="4" height="4" fill={A_TOKENS.goldDim} opacity="0.5" />
            </svg>
            <span style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.parchmentDim }}>The Grimwood Tavern</span>
          </div>
          <div style={{ fontFamily: "'IM Fell English', serif", fontSize: 10, color: A_TOKENS.dimText, marginTop: 4, fontStyle: "italic", lineHeight: 1.5 }}>
            A crossroads inn at the edge of the old forest. Three known NPCs present.
          </div>
        </div>

        <div style={{ flex: 1 }} />

        {/* Inventory hint */}
        <div style={{ borderTop: `1px solid ${A_TOKENS.border}`, paddingTop: 10, marginTop: 10 }}>
          {["Longsword","Chain Mail","Healer's Kit","30 gp"].map((item, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
              <div style={{ width: 3, height: 3, background: A_TOKENS.borderGold, transform: "rotate(45deg)", flexShrink: 0 }} />
              <span style={{ fontFamily: "'IM Fell English', serif", fontSize: 10, color: A_TOKENS.dimText }}>{item}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Main session view */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", position: "relative", zIndex: 1 }}>
        {/* Header */}
        <div style={{
          borderBottom: `1px solid ${A_TOKENS.border}`,
          padding: "12px 20px",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          background: A_TOKENS.bgDeep,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
              <polygon points="11,1 21,6 21,16 11,21 1,16 1,6" stroke={A_TOKENS.gold} strokeWidth="1" fill="none" />
              <polygon points="11,5 17,8 17,14 11,17 5,14 5,8" stroke={A_TOKENS.borderGold} strokeWidth="0.5" fill={A_TOKENS.bgDeep} />
              <text x="11" y="14" textAnchor="middle" fill={A_TOKENS.gold} fontSize="8" fontFamily="serif">C</text>
            </svg>
            <div>
              <div style={{ fontFamily: "'Cinzel', serif", fontSize: 13, color: A_TOKENS.gold, letterSpacing: 1 }}>The Tavern at Grimwood Crossing</div>
              <div style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: A_TOKENS.dimText, letterSpacing: 2 }}>SESSION I · TURN 4</div>
            </div>
          </div>
          <div style={{ display: "flex", gap: 16, alignItems: "center" }}>
            {["Lore", "Party", "Map"].map(l => (
              <button key={l} style={{ background: "none", border: "none", fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText, letterSpacing: 2, cursor: "pointer", textTransform: "uppercase", padding: 0 }}>{l}</button>
            ))}
            <div style={{ width: 1, height: 16, background: A_TOKENS.border }} />
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: A_TOKENS.success, boxShadow: `0 0 6px ${A_TOKENS.success}` }} />
          </div>
        </div>

        {/* Scene header */}
        <div style={{
          padding: "16px 24px 12px",
          borderBottom: `1px solid ${A_TOKENS.border}`,
          background: `linear-gradient(to bottom, rgba(30,24,18,0.5), transparent)`,
        }}>
          <div style={{ fontFamily: "'IM Fell English', serif", fontSize: 12, color: A_TOKENS.dimText, fontStyle: "italic", letterSpacing: 1, marginBottom: 4 }}>
            ❧ Scene I — The Weary Road
          </div>
          <div style={{ fontFamily: "'Cinzel', serif", fontSize: 18, color: A_TOKENS.parchment, letterSpacing: 1 }}>
            The Barroom Floor
          </div>
        </div>

        {/* Transcript */}
        <div ref={scrollRef} style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 4 }}>
          {turns.map((turn, i) => (
            <TurnBubble key={i} turn={turn} onRoll={handleRoll} />
          ))}
        </div>

        {/* Input */}
        <div style={{
          borderTop: `1px solid ${A_TOKENS.border}`,
          padding: "14px 20px",
          background: A_TOKENS.bgDeep,
        }}>
          <div style={{ marginBottom: 8, display: "flex", gap: 8 }}>
            {["Ask about Kael", "Buy a drink", "Leave quietly"].map(s => (
              <button key={s} onClick={() => setInput(s)} style={{
                background: "none",
                border: `1px solid ${A_TOKENS.border}`,
                color: A_TOKENS.dimText,
                fontFamily: "'IM Fell English', serif",
                fontSize: 11,
                padding: "3px 10px",
                cursor: "pointer",
                fontStyle: "italic",
              }}>{s}</button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
            <textarea
              value={input}
              onChange={e => setInput(e.target.value)}
              placeholder="Describe your action..."
              style={{
                flex: 1,
                background: A_TOKENS.ink,
                border: `1px solid ${A_TOKENS.borderGold}`,
                color: A_TOKENS.parchment,
                fontFamily: "'IM Fell English', serif",
                fontSize: 13,
                padding: "10px 14px",
                resize: "none",
                height: 56,
                outline: "none",
                fontStyle: "italic",
                lineHeight: 1.6,
              }}
            />
            <button style={{
              background: A_TOKENS.bgDeep,
              border: `1px solid ${A_TOKENS.gold}`,
              color: A_TOKENS.gold,
              fontFamily: "'Cinzel', serif",
              fontSize: 10,
              letterSpacing: 2,
              padding: "0 18px",
              cursor: "pointer",
              textTransform: "uppercase",
            }}>
              Act
            </button>
          </div>
        </div>
      </div>

      {/* Right sidebar — world lore */}
      <div style={{
        width: 180,
        background: A_TOKENS.bgDeep,
        borderLeft: `1px solid ${A_TOKENS.border}`,
        padding: "20px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 0,
        flexShrink: 0,
        zIndex: 1,
      }}>
        <div style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText, letterSpacing: 3, marginBottom: 12, textTransform: "uppercase" }}>Known Lore</div>

        {[
          { type: "NPC", name: "Old Grim", note: "Retired soldier. Gruff. Few words." },
          { type: "NPC", name: "The Stranger", note: "Hooded figure. Watching." },
          { type: "PLACE", name: "Mill Road North", note: "Kael was seen heading this way." },
          { type: "QUEST", name: "Find Kael", note: "Missing merchant. Owes Grim 30gp." },
        ].map((e, i) => (
          <div key={i} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 3 }}>
              <span style={{ fontFamily: "'Cinzel', serif", fontSize: 7, color: A_TOKENS.ember, letterSpacing: 1, border: `1px solid ${A_TOKENS.ember}`, padding: "1px 4px", opacity: 0.7 }}>{e.type}</span>
              <span style={{ fontFamily: "'Cinzel', serif", fontSize: 10, color: A_TOKENS.parchmentDim }}>{e.name}</span>
            </div>
            <div style={{ fontFamily: "'IM Fell English', serif", fontSize: 10, color: A_TOKENS.dimText, fontStyle: "italic", lineHeight: 1.5, paddingLeft: 8, borderLeft: `1px solid ${A_TOKENS.border}` }}>{e.note}</div>
          </div>
        ))}

        <OrnamentDivider />

        <div style={{ fontFamily: "'Cinzel', serif", fontSize: 9, color: A_TOKENS.dimText, letterSpacing: 3, margin: "8px 0 10px", textTransform: "uppercase" }}>NPC Status</div>
        {[
          { name: "Old Grim", mood: "Neutral", color: A_TOKENS.dimText },
          { name: "The Stranger", mood: "Watching", color: A_TOKENS.ember },
          { name: "Town Guard", mood: "Suspicious", color: "#8a6a30" },
        ].map((n, i) => (
          <div key={i} style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
            <span style={{ fontFamily: "'IM Fell English', serif", fontSize: 11, color: A_TOKENS.parchmentDim }}>{n.name}</span>
            <span style={{ fontFamily: "'Cinzel', serif", fontSize: 8, color: n.color, letterSpacing: 1 }}>{n.mood}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

Object.assign(window, { DirectionA });
