import type { SimScreen } from "./simulator";

export function PhoneSimulator({ screen }: { screen: SimScreen | null }) {
  return (
    <section className="phone" aria-label="Phone simulator">
      <div className="phone__frame">
        <div className="phone__status">
          <span>9:41</span>
          <span>5G</span>
        </div>
        <div className="phone__screen">
          <h2 className="phone__app">Settings</h2>
          {screen === null ? (
            <p className="phone__empty">Press Open on a step and the screen it points to appears here.</p>
          ) : (
            <div key={screen.uri} className="phone__panel">
              <h3 className="phone__title">{screen.title}</h3>
              {screen.kind === "toggle" && (
                <label className="switch">
                  <input type="checkbox" role="switch" checked={screen.on === true} readOnly aria-label={screen.title} />
                  <span className="switch__track" />
                </label>
              )}
              {screen.kind === "slider" && <input type="range" className="slider" defaultValue={60} aria-label={screen.title} />}
              <p className="phone__note">{screen.note}</p>
              {screen.verifiedKey && <p className="phone__verified">Verified: {screen.verifiedKey}</p>}
              <code className="phone__uri">{screen.uri}</code>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
