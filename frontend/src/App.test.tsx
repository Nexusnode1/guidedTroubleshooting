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
          actionableDeeplink: { deeplink: "voiceassist://masked/act/14eb42b895", description: "d", message: "Enable Touch sensitivity", originalType: "onURL" },
          validationDeeplink: { deeplink: "voiceassist://masked/val/6451858b28", key: "Touch sensitivity" },
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
  await userEvent.click(screen.getByRole("button", { name: "Find solution" }));
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
    expect(screen.getByText(/cached verified match/i)).toBeInTheDocument();
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

  it("sends siis_response when the advanced text area is filled in", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Advanced troubleshooting source"));
    await userEvent.type(screen.getByLabelText(/raw troubleshooting text/i), "## Step\nGo to Settings. Tap Battery.");
    await send("my battery drains fast");
    await screen.findByText(plan.response.contexts[0].goal);
    const body = lastRequestBody();
    expect(body.query).toBe("my battery drains fast");
    expect(body.siis_response).toBe("## Step\nGo to Settings. Tap Battery.");
  });

  it("fills in the verified Battery example and reaches the cold path", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Advanced troubleshooting source"));
    await userEvent.click(screen.getByRole("button", { name: /battery example/i }));
    expect(screen.getByLabelText("Describe your problem")).toHaveValue(
      "My Galaxy phone's battery is draining much faster than it used to.",
    );
    const coldPathValue = (screen.getByLabelText(/raw troubleshooting text/i) as HTMLTextAreaElement).value;
    expect(coldPathValue).toContain("Troubleshooting Fast Battery Drain");
    await userEvent.click(screen.getByRole("button", { name: "Find solution" }));
    await screen.findByText(plan.response.contexts[0].goal);
    const body = lastRequestBody();
    expect(body.query).toBe("My Galaxy phone's battery is draining much faster than it used to.");
    expect(body.siis_response).toContain("Troubleshooting Fast Battery Drain");
  });

  it("labels a reply built from provided source text differently from a cached reply", async () => {
    render(<App />);
    await userEvent.click(screen.getByText("Advanced troubleshooting source"));
    await userEvent.type(screen.getByLabelText(/raw troubleshooting text/i), "## Step\nGo to Settings. Tap Battery.");
    await send("my battery drains fast");
    await screen.findByText(plan.response.contexts[0].goal);
    expect(screen.getByText(/newly analyzed from the text you provided/i)).toBeInTheDocument();
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

  it("explains an empty result and offers example chips to retry with", async () => {
    mockFetch({ ...plan, response: { contexts: [] }, meta: { ...plan.meta, fallback: "no_match", cache_hit: false } });
    render(<App />);
    await send("best pasta recipe");
    expect(await screen.findByText(/let's narrow that down/i)).toBeInTheDocument();
    expect(screen.getByText(/couldn't find a verified troubleshooting flow/i)).toBeInTheDocument();
    expect(screen.getByText(/what best describes the problem/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Screen is completely black" })).toBeInTheDocument();
  });

  it("distinguishes a truly empty knowledge base from an ordinary no-match", async () => {
    mockFetch({
      ...plan,
      response: { contexts: [] },
      meta: { ...plan.meta, fallback: "no_siis_context", cache_hit: false },
    });
    render(<App />);
    await send("anything");
    expect(await screen.findByText(/no verified troubleshooting content loaded/i)).toBeInTheDocument();
  });

  it("shows a generic error with no implementation detail or stack trace", async () => {
    mockFetch({}, false);
    render(<App />);
    await send("touch is laggy");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/something went wrong/i);
    expect(alert).toHaveTextContent(/please try again/i);
    expect(alert.textContent).not.toMatch(/engine|rules-v1|at \S+\.tsx?:\d+/i);
  });

  it("retries the same query when Try again is clicked after a failure", async () => {
    mockFetch({}, false);
    render(<App />);
    await send("touch is laggy");
    await screen.findByRole("alert");
    mockFetch(plan);
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    await screen.findByText(plan.response.contexts[0].goal);
    expect(lastRequestBody().query).toBe("touch is laggy");
  });

  it("sends a clarification chip as a normal new query, not a bypass of the backend", async () => {
    mockFetch({ ...plan, response: { contexts: [] }, meta: { ...plan.meta, fallback: "no_match", cache_hit: false } });
    render(<App />);
    await send("my phone has a problem");
    await screen.findByText(/let's narrow that down/i);
    mockFetch(plan);
    await userEvent.click(screen.getByRole("button", { name: "Touch isn't responding" }));
    await screen.findByText(plan.response.contexts[0].goal);
    expect(lastRequestBody().query).toBe("Touch isn't responding");
  });

  it("offers example queries beneath the composer that run immediately", async () => {
    render(<App />);
    await userEvent.click(screen.getByRole("button", { name: "Screen won't turn on" }));
    await screen.findByText(plan.response.contexts[0].goal);
    expect(lastRequestBody().query).toBe("Screen won't turn on");
  });
});
