import { describe, expect, it } from "vitest";
import { openDeeplink } from "./simulator";

const base = { deeplink: "bixby://masked/act/14eb42b895", description: "d" };

describe("openDeeplink", () => {
  it("turns a toggle on for onURL and names the setting", () => {
    const screen = openDeeplink({ ...base, message: "Enable Touch sensitivity", originalType: "onURL" });
    expect(screen).toMatchObject({ title: "Touch sensitivity", kind: "toggle", on: true, note: "Turned on" });
  });

  it("turns a toggle off for offURL", () => {
    const screen = openDeeplink({ ...base, message: "Disable Touch sensitivity", originalType: "offURL" });
    expect(screen).toMatchObject({ kind: "toggle", on: false, note: "Turned off" });
  });

  it("opens a plain page for onClickURL", () => {
    const screen = openDeeplink({ ...base, message: "View Navigation bar", originalType: "onClickURL" });
    expect(screen).toMatchObject({ title: "Navigation bar", kind: "page", on: null, note: "Opened" });
  });

  it("shows a slider for updateURL", () => {
    const screen = openDeeplink({ ...base, message: "Adjust Brightness", originalType: "updateURL" });
    expect(screen).toMatchObject({ title: "Brightness", kind: "slider", note: "Adjusted" });
  });

  it("carries the validation label and the untouched URI", () => {
    const screen = openDeeplink(
      { ...base, message: "View Wi-Fi", originalType: "onClickURL" },
      { deeplink: "bixby://masked/val/x", key: "Wi-Fi" },
    );
    expect(screen.verifiedKey).toBe("Wi-Fi");
    expect(screen.uri).toBe("bixby://masked/act/14eb42b895");
  });

  it("falls back to the description, then to Settings, when there is no message", () => {
    expect(openDeeplink({ ...base, description: "Opens the Storage Settings screen", originalType: "placeholder" }).title)
      .toBe("Storage Settings screen");
    expect(openDeeplink({ deeplink: "bixby://x", description: "", message: "" }).title).toBe("Settings");
  });
});
