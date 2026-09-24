import { FormEvent, useEffect, useRef, useState } from "react";
import { troubleshoot } from "./api";
import { PhoneSimulator } from "./PhoneSimulator";
import { PlanCard } from "./PlanCard";
import { openDeeplink, type SimScreen } from "./simulator";
import type { TroubleshootResponse } from "./types";

type Message =
  | { id: number; role: "user"; text: string }
  | { id: number; role: "bot"; data: TroubleshootResponse; usedColdPath: boolean }
  | { id: number; role: "error"; text: string };

// Each of these is verified against the live service (see docs/demo_readiness.md) to
// return a plan whose steps actually match the stated symptom -- the previous cracked +
// flickers combination hit a camera-video-flicker plan whose steps ("disable Super steady
// mode", "adjust shutter speed") have nothing to do with a cracked screen.
const EXAMPLES = [
  "My screen is cracked",
  "Touch responses are laggy",
  "Screen stays black when I turn it on",
];

// Verbatim from tests/fixtures/cross_domain_articles.json's "battery_drain_fast" article
// (a clearly labeled SYNTHETIC DOMAIN GENERALIZATION FIXTURE, not official data), used
// unmodified as a ready-made cold-path example -- Battery is outside the official Display
// dataset, so this also doubles as evidence the pipeline is not Display-specific.
const BATTERY_EXAMPLE = {
  query: "My Galaxy phone's battery is draining much faster than it used to.",
  siisResponse:
    "Smartphone,Others Mobile Battery drains unusually fast on your Galaxy phone " +
    "( Smartphone,Others Mobile): # Troubleshooting Fast Battery Drain\n" +
    "## Turn On Power Saving\nGo to Settings. Tap Battery. Tap the switch next to Power saving to turn it on.\n" +
    "## Enable Adaptive Battery\nGo to Settings. Tap Battery. Tap the switch next to Adaptive battery to enable it.\n" +
    "## Put Unused Apps To Sleep\nGo to Settings. Tap Battery. Tap Put unused apps to sleep.\n" +
    "## Restart Your Device\nPress and hold the Power button, then tap Restart. Tap Restart again to confirm.\n",
};

function MetaStrip({ data, usedColdPath }: { data: TroubleshootResponse; usedColdPath: boolean }) {
  const { latency_ms, cache_hit, model, cost_usd } = data.meta;
  const pathLabel = usedColdPath ? "cold path (raw text supplied)" : cache_hit ? "cache hit" : "cache miss";
  return (
    <p className="meta">
      {pathLabel} · {latency_ms} ms · {model} · ${cost_usd.toFixed(2)}
    </p>
  );
}

export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [coldPathText, setColdPathText] = useState("");
  const [busy, setBusy] = useState(false);
  const [screen, setScreen] = useState<SimScreen | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(1);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [messages, busy]);

  async function send(text: string) {
    const query = text.trim();
    if (!query || busy) return;
    const usedColdPath = coldPathText.trim() !== "";
    setDraft("");
    setBusy(true);
    setMessages((current) => [...current, { id: nextId.current++, role: "user", text: query }]);
    try {
      const data = await troubleshoot(query, coldPathText);
      setMessages((current) => [...current, { id: nextId.current++, role: "bot", data, usedColdPath }]);
    } catch (error) {
      const text = error instanceof Error ? error.message : "The engine could not be reached.";
      setMessages((current) => [...current, { id: nextId.current++, role: "error", text }]);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  function fillBatteryExample() {
    setDraft(BATTERY_EXAMPLE.query);
    setColdPathText(BATTERY_EXAMPLE.siisResponse);
  }

  return (
    <div className="app">
      <main className="chat">
        <header className="chat__head">
          <h1>Galaxy Troubleshooter</h1>
          <p>Describe what's wrong in your own words. You'll get an ordered plan you can open step by step.</p>
        </header>

        <div className="thread" aria-live="polite">
          {messages.length === 0 && (
            <div className="examples">
              {EXAMPLES.map((example) => (
                <button key={example} type="button" className="chip" onClick={() => void send(example)}>
                  {example}
                </button>
              ))}
            </div>
          )}
          {messages.map((message) => {
            if (message.role === "user") return <p key={message.id} className="bubble bubble--user">{message.text}</p>;
            if (message.role === "error") return <p key={message.id} role="alert" className="bubble bubble--error">{message.text}</p>;
            const contexts = message.data.response.contexts;
            return (
              <div key={message.id} className="bubble bubble--bot">
                {contexts.length === 0 ? (
                  <p>I couldn't find a verified fix for that. Try describing the symptom or the screen you're on.</p>
                ) : (
                  contexts.map((goal) => (
                    <PlanCard
                      key={goal.goal}
                      goal={goal}
                      activeUri={screen?.uri ?? null}
                      onOpen={(link, validation) => setScreen(openDeeplink(link, validation))}
                    />
                  ))
                )}
                <MetaStrip data={message.data} usedColdPath={message.usedColdPath} />
              </div>
            );
          })}
          {busy && <p className="bubble bubble--bot bubble--pending">Working on it…</p>}
          <div ref={endRef} />
        </div>

        <details className="cold-path">
          <summary>Paste raw troubleshooting text (cold path demo)</summary>
          <p className="cold-path__hint">
            Optional. When this is filled in, the next message skips the semantic cache and builds a
            fresh plan straight from this text instead.
          </p>
          <textarea
            className="cold-path__text"
            aria-label="Raw troubleshooting text (siis_response)"
            value={coldPathText}
            onChange={(event) => setColdPathText(event.target.value)}
            placeholder="Paste article-style troubleshooting text here…"
            rows={4}
          />
          <button type="button" className="chip" onClick={fillBatteryExample}>
            Fill in the Battery example
          </button>
        </details>

        <form className="composer" onSubmit={onSubmit}>
          <input
            aria-label="Describe your problem"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="e.g. my screen flickers after the update"
            autoComplete="off"
          />
          <button type="submit" disabled={busy || draft.trim() === ""}>Send</button>
        </form>
      </main>

      <aside className="side">
        <PhoneSimulator screen={screen} />
      </aside>
    </div>
  );
}
