import type { ActionableDeeplink, ValidationDeeplink } from "./types";

export type ScreenKind = "toggle" | "page" | "slider";

export interface SimScreen {
  uri: string;
  title: string;
  kind: ScreenKind;
  on: boolean | null;
  verifiedKey: string | null;
  note: string;
}

const VERB_PREFIX = /^(?:view|enables?|disables?|adjust|increase|check|opens?|sets?)\s+(?:the\s+)?/i;

/** Pure model of what a deeplink does on a Galaxy Settings screen. The URI is carried, never navigated to. */
export function openDeeplink(link: ActionableDeeplink, validation?: ValidationDeeplink | null): SimScreen {
  const type = link.originalType ?? "";
  const title = (link.message || link.description).replace(VERB_PREFIX, "").trim() || "Settings";
  const kind: ScreenKind = type === "onURL" || type === "offURL" ? "toggle" : type === "updateURL" ? "slider" : "page";
  const on = type === "onURL" ? true : type === "offURL" ? false : null;
  const note = kind === "toggle" ? (on ? "Turned on" : "Turned off") : kind === "slider" ? "Adjusted" : "Opened";
  return { uri: link.deeplink, title, kind, on, verifiedKey: validation?.key ?? null, note };
}
