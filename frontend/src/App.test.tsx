import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

const plan = {
  query: "touch is laggy",
  query_variations: ["a", "b", "c", "d", "e", "f", "g", "h"],
  response: {
    contexts: [{
      goal: "Follow these steps to perform this Touchscreen Issues Troubleshooting",
      title: "Touchscreen issues",
      score: 0.9,
      actions: [{
        actionName: "Touch Sensitivity Setting",
        description: "It will help with touch sensitivity setting",
        category: "auto",
        stepGroups: [{
          steps: ["Go to Settings.", "Tap Display."],
          actionableDeeplink: { deeplink: "bixby://masked/act/14eb42b895", description: "d", message: "Enable Touch sensitivity", originalType: "onURL" },
          validationDeeplink: { deeplink: "bixby://masked/val/6451858b28", key: "Touch sensitivity" },
        }],
      }],
    }],
  },
  meta: { latency_ms: 12, cache_hit: true, model: "rules-v1", cost_usd: 0 },
};

function mockFetch(body: unknown, ok = true) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok, status: ok ? 200 : 500, json: async () => body }));
}

beforeEach(() => mockFetch(plan));
afterEach(() => vi.unstubAllGlobals());

async function send(text: string) {
  await userEvent.type(screen.getByLabelText("Describe your problem"), text);
  await userEvent.click(screen.getByRole("button", { name: "Send" }));
}

function lastRequestBody(): { query: string; siis_response?: string } {
  const mocked = vi.mocked(fetch);
  const call = mocked.mock.calls[mocked.mock.calls.length - 1];
  const init = call[1] as RequestInit;
  return JSON.parse(init.body as string);
}

describe("App", () => {
  it("sends the message, renders the plan and its meta strip", async () => {
    render(<App />);
    await send("touch is laggy");
    expect(await screen.findByText(plan.response.contexts[0].goal)).toBeInTheDocument();
    expect(screen.getByText(/12 ms/)).toBeInTheDocument();
    expect(screen.getByText(/cache hit/)).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledWith("/v1/troubleshoot", expect.objectContaining({ method: "POST" }));
  });

  it("preserves the normal query flow when the cold-path text is empty", async () => {
    render(<App />);
    await send("touch is laggy");
    await screen.findByText(plan.response.contexts[0].goal);
    const body = lastRequestBody();
    expect(body.query).toBe("touch is laggy");
    expect(body).not.toHaveProperty("siis_response");
  });

  it("sends siis_response when the cold-path text area is filled in", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Paste raw troubleshooting text (cold path demo)"));
    await userEvent.type(screen.getByLabelText(/raw troubleshooting text/i), "## Step\nGo to Settings. Tap Battery.");
    await send("my battery drains fast");
    await screen.findByText(plan.response.contexts[0].goal);
    const body = lastRequestBody();
    expect(body.query).toBe("my battery drains fast");
    expect(body.siis_response).toBe("## Step\nGo to Settings. Tap Battery.");
  });

  it("fills in the verified Battery example and reaches the cold path", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Paste raw troubleshooting text (cold path demo)"));
    await userEvent.click(screen.getByRole("button", { name: /battery example/i }));
    expect(screen.getByLabelText("Describe your problem")).toHaveValue(
      "My Galaxy phone's battery is draining much faster than it used to.",
    );
    const coldPathValue = (screen.getByLabelText(/raw troubleshooting text/i) as HTMLTextAreaElement).value;
    expect(coldPathValue).toContain("Troubleshooting Fast Battery Drain");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText(plan.response.contexts[0].goal);
    const body = lastRequestBody();
    expect(body.query).toBe("My Galaxy phone's battery is draining much faster than it used to.");
    expect(body.siis_response).toContain("Troubleshooting Fast Battery Drain");
  });

  it("labels a reply that used the cold path differently from a normal cached reply", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Paste raw troubleshooting text (cold path demo)"));
    await userEvent.type(screen.getByLabelText(/raw troubleshooting text/i), "## Step\nGo to Settings. Tap Battery.");
    await send("my battery drains fast");
    await screen.findByText(plan.response.contexts[0].goal);
    expect(screen.getByText(/cold path \(raw text supplied\)/i)).toBeInTheDocument();
  });

  it("drives the phone simulator from the Open button", async () => {
    render(<App />);
    await send("touch is laggy");
    await userEvent.click(await screen.findByRole("button", { name: "Open Enable Touch sensitivity" }));
    const phone = screen.getByLabelText("Phone simulator");
    expect(within(phone).getByText("Touch sensitivity")).toBeInTheDocument();
    expect(within(phone).getByText("Turned on")).toBeInTheDocument();
    expect(within(phone).getByText(/Verified: Touch sensitivity/)).toBeInTheDocument();
  });

  it("explains an empty result", async () => {
    mockFetch({ ...plan, response: { contexts: [] }, meta: { ...plan.meta, fallback: "no_match", cache_hit: false } });
    render(<App />);
    await send("best pasta recipe");
    expect(await screen.findByText(/couldn't find a verified fix/i)).toBeInTheDocument();
  });

  it("shows a friendly error when the engine is unreachable", async () => {
    mockFetch({}, false);
    render(<App />);
    await send("touch is laggy");
    expect(await screen.findByRole("alert")).toHaveTextContent(/engine/i);
  });
});
