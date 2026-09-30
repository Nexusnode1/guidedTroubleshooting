import { FormEvent, KeyboardEvent, useRef, useState } from "react";
import { troubleshoot } from "./api";
import { ChevronIcon, DiagnosticGlyph, SearchIcon, ShieldCheckIcon, WrenchIcon } from "./icons";
import { PhoneSimulator } from "./PhoneSimulator";
import { PlanCard } from "./PlanCard";
import { openDeeplink, type SimScreen } from "./simulator";
import type { ActionableDeeplink, TroubleshootResponse, ValidationDeeplink } from "./types";

type OpenHandler = (link: ActionableDeeplink, validation: ValidationDeeplink | null | undefined) => void;

// Shown under the composer at all times the page is idle. Deliberately a mix: some of these
// resolve to a verified plan against the live service, some (Camera, Battery, Bluetooth)
// currently do not -- they demonstrate the "no verified match" state honestly rather than
// being cherry-picked to always succeed. Examples are illustrations of how to phrase a query,
// not a promise that every one resolves.
const EXAMPLES = ["Screen won't turn on", "Camera won't open", "Battery drains quickly", "Bluetooth won't connect"];

// Shown inside the "no verified match" state: symptom phrasings (not full queries) meant to
// help someone reformulate, not a detected "ambiguous" backend state -- the API has no such
// signal, so this never bypasses backend validation; picking one just sends it as a normal
// new query through the same troubleshoot() call every other query goes through.
const CLARIFICATION_CHIPS = [
  "Screen is completely black",
  "Screen is flickering",
  "Touch isn't responding",
  "Only part of the screen works",
];

// Verbatim from tests/fixtures/cross_domain_articles.json's "battery_drain_fast" article
// (a clearly labeled SYNTHETIC DOMAIN GENERALIZATION FIXTURE, not official data), used
// unmodified as a ready-made source-text example for the advanced section below.
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

type Result =
  | { kind: "idle" }
  | { kind: "busy"; query: string }
  | { kind: "success"; query: string; data: TroubleshootResponse; usedColdPath: boolean }
  | { kind: "empty"; query: string; reason: "no_match" | "no_siis_context" }
  | { kind: "error"; query: string; message: string };

function ExampleChips({ items, onPick }: { items: string[]; onPick: (example: string) => void }) {
  return (
    <div className="examples">
      {items.map((example) => (
        <button key={example} type="button" className="chip" onClick={() => onPick(example)}>
          {example}
        </button>
      ))}
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="result-panel result-panel--loading" role="status">
      <span className="spinner" aria-hidden="true" />
      <p>Finding a verified troubleshooting flow…</p>
    </div>
  );
}

function ErrorPanel({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="result-panel result-panel--error" role="alert">
      <p className="result-panel__title">Something went wrong</p>
      <p>Please try again.</p>
      <button type="button" className="retry" onClick={onRetry}>
        Try again
      </button>
    </div>
  );
}

function EmptyPanel({
  query,
  reason,
  onExample,
  onOpenAdvanced,
}: {
  query: string;
  reason: "no_match" | "no_siis_context";
  onExample: (example: string) => void;
  onOpenAdvanced: () => void;
}) {
  return (
    <div className="result-panel result-panel--empty">
      <p className="result-panel__query">You asked: “{query}”</p>
      <div className="result-panel__icon" aria-hidden="true">
        <SearchIcon width={28} height={28} />
      </div>
      <h2 className="result-panel__title">Let's narrow that down</h2>
      {reason === "no_siis_context" ? (
        <p>
          There's no verified troubleshooting content loaded for this yet.{" "}
          <button type="button" className="link-button" onClick={onOpenAdvanced}>
            Open the advanced section
          </button>{" "}
          below and add some, or try a different phrasing.
        </p>
      ) : (
        <>
          <p>We couldn't find a verified troubleshooting flow for this description.</p>
          <p className="result-panel__tips-label">Try adding:</p>
          <ul className="result-panel__tips">
            <li>the exact symptom</li>
            <li>the screen or setting you are on</li>
            <li>what happened immediately before the problem</li>
          </ul>
          <p className="result-panel__clarify">I want to make sure I point you to the right fix.</p>
          <p className="examples__label">What best describes the problem?</p>
          <ExampleChips items={CLARIFICATION_CHIPS} onPick={onExample} />
        </>
      )}
    </div>
  );
}

function DetailsBlock({ data, usedColdPath }: { data: TroubleshootResponse; usedColdPath: boolean }) {
  const source = usedColdPath ? "Newly analyzed from the text you provided" : "Cached verified match";
  return (
    <details className="result-details">
      <summary>Details</summary>
      <p className="details__row">Response time: {data.meta.latency_ms} ms</p>
      <p className="details__row">Verified source: {source}</p>
    </details>
  );
}

function SuccessPanel({
  query,
  data,
  usedColdPath,
  activeUri,
  onOpen,
}: {
  query: string;
  data: TroubleshootResponse;
  usedColdPath: boolean;
  activeUri: string | null;
  onOpen: OpenHandler;
}) {
  return (
    <div className="result-panel result-panel--success">
      <p className="result-panel__query">You asked: “{query}”</p>
      {data.response.contexts.map((goal) => (
        <PlanCard key={goal.goal} goal={goal} activeUri={activeUri} onOpen={onOpen} />
      ))}
      <DetailsBlock data={data} usedColdPath={usedColdPath} />
    </div>
  );
}

export default function App() {
  const [result, setResult] = useState<Result>({ kind: "idle" });
  const [draft, setDraft] = useState("");
  const [coldPathText, setColdPathText] = useState("");
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const [screen, setScreen] = useState<SimScreen | null>(null);
  const advancedRef = useRef<HTMLDetailsElement>(null);

  const busy = result.kind === "busy";

  async function send(text: string) {
    const query = text.trim();
    if (!query || busy) return;
    const usedColdPath = coldPathText.trim() !== "";
    setDraft("");
    setResult({ kind: "busy", query });
    try {
      const data = await troubleshoot(query, coldPathText);
      const contexts = data.response.contexts;
      if (contexts.length === 0) {
        const reason = data.meta.fallback === "no_siis_context" ? "no_siis_context" : "no_match";
        setResult({ kind: "empty", query, reason });
      } else {
        setResult({ kind: "success", query, data, usedColdPath });
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "The engine could not be reached.";
      setResult({ kind: "error", query, message });
    }
  }

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    void send(draft);
  }

  function onComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      void send(draft);
    }
  }

  function retry() {
    if (result.kind === "error") void send(result.query);
  }

  function fillBatteryExample() {
    setDraft(BATTERY_EXAMPLE.query);
    setColdPathText(BATTERY_EXAMPLE.siisResponse);
  }

  function openAdvanced() {
    setAdvancedOpen(true);
    advancedRef.current?.scrollIntoView?.({ behavior: "smooth", block: "center" });
  }

  return (
    <div className="app">
      <div className="main">
        <header className="page-header">
          <span className="page-header__mark" aria-hidden="true">
            <ShieldCheckIcon />
          </span>
          <div>
            <p className="page-header__name">Troubleshooting Assistant</p>
            <p className="page-header__tagline">Verified device guidance</p>
          </div>
        </header>

        <section className="hero">
          <DiagnosticGlyph className="hero__glyph" />
          <h1>Troubleshoot your device</h1>
          <p>Describe what's happening and we'll find a verified troubleshooting flow.</p>

          <form className="composer" onSubmit={onSubmit}>
            <label className="field-label" htmlFor="query-input">
              Describe your problem
            </label>
            <div className="composer__row">
              <WrenchIcon className="composer__icon" />
              <textarea
                id="query-input"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                onKeyDown={onComposerKeyDown}
                placeholder="Describe your problem..."
                rows={2}
                disabled={busy}
                autoComplete="off"
              />
              <button type="submit" disabled={busy || draft.trim() === ""}>
                Find solution
              </button>
            </div>
          </form>

          {result.kind === "idle" && (
            <div className="examples-row">
              <p className="examples__label">Try an example</p>
              <ExampleChips items={EXAMPLES} onPick={(example) => void send(example)} />
            </div>
          )}
        </section>

        <div className="result-area" aria-live="polite">
          {result.kind === "busy" && <LoadingPanel />}
          {result.kind === "success" && (
            <SuccessPanel
              query={result.query}
              data={result.data}
              usedColdPath={result.usedColdPath}
              activeUri={screen?.uri ?? null}
              onOpen={(link, validation) => setScreen(openDeeplink(link, validation))}
            />
          )}
          {result.kind === "empty" && (
            <EmptyPanel
              query={result.query}
              reason={result.reason}
              onExample={(example) => void send(example)}
              onOpenAdvanced={openAdvanced}
            />
          )}
          {result.kind === "error" && <ErrorPanel onRetry={retry} />}
        </div>

        <details
          className="advanced"
          ref={advancedRef}
          open={advancedOpen}
          onToggle={(event) => setAdvancedOpen(event.currentTarget.open)}
        >
          <summary>
            Advanced troubleshooting source
            <ChevronIcon className="advanced__chevron" />
          </summary>
          <p className="advanced__hint">
            Optional. When this is filled in, the next message skips the cache and builds a fresh plan
            straight from this text instead.
          </p>
          <label className="field-label" htmlFor="cold-path-text">
            Raw troubleshooting text
          </label>
          <textarea
            id="cold-path-text"
            className="advanced__text"
            value={coldPathText}
            onChange={(event) => setColdPathText(event.target.value)}
            placeholder="Paste article-style troubleshooting text here…"
            rows={4}
          />
          <button type="button" className="chip" onClick={fillBatteryExample}>
            Fill in the Battery example
          </button>
        </details>

        <footer className="page-footer">
          <p>Guidance is limited to verified troubleshooting content. No steps are invented.</p>
        </footer>
      </div>

      <aside className="side">
        <PhoneSimulator screen={screen} />
      </aside>
    </div>
  );
}
