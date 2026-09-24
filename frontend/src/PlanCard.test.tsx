import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PlanCard } from "./PlanCard";
import type { Goal } from "./types";

const link = {
  deeplink: "bixby://masked/act/14eb42b895",
  description: "Enables touch sensitivity via device Settings on the device.",
  message: "Enable Touch sensitivity",
  originalType: "onURL",
};
const validation = { deeplink: "bixby://masked/val/6451858b28", key: "Touch sensitivity", resultType: "boolean", condition: "equal", value: "True" };

const goal: Goal = {
  goal: "Follow these steps to perform this Touchscreen Issues Troubleshooting",
  title: "Touchscreen issues",
  score: 0.9,
  actions: [
    { actionName: "Touch Sensitivity Setting", description: "It will help with touch sensitivity setting", category: "auto",
      stepGroups: [{ steps: ["Go to Settings.", "Tap Display."], actionableDeeplink: link, validationDeeplink: validation }] },
    { actionName: "Charger Issues", description: "It will help with charger issues", category: "manual",
      stepGroups: [{ steps: ["Try using a different, undamaged charger."], actionableDeeplink: null, validationDeeplink: null }] },
    { actionName: "Factory Data Reset", description: "It will help you factory data reset", category: "critical",
      stepGroups: [{ steps: ["Tap Reset."], actionableDeeplink: null, validationDeeplink: null }] },
  ],
};

describe("PlanCard", () => {
  it("shows the goal, every action, and its numbered steps", () => {
    render(<PlanCard goal={goal} activeUri={null} onOpen={() => {}} />);
    expect(screen.getByText(goal.goal)).toBeInTheDocument();
    expect(screen.getByText("Touch Sensitivity Setting")).toBeInTheDocument();
    expect(screen.getByText("Tap Display.")).toBeInTheDocument();
    expect(screen.getByText("auto")).toBeInTheDocument();
    expect(screen.getByText("manual")).toBeInTheDocument();
    expect(screen.getByText("critical")).toBeInTheDocument();
  });

  it("offers Open only on actions that carry a deeplink, and reports it with its validation", async () => {
    const onOpen = vi.fn();
    render(<PlanCard goal={goal} activeUri={null} onOpen={onOpen} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Open Enable Touch sensitivity" }));
    expect(onOpen).toHaveBeenCalledWith(link, validation);
  });

  it("warns before a critical action", () => {
    render(<PlanCard goal={goal} activeUri={null} onOpen={() => {}} />);
    expect(screen.getByText(/back up your data first/i)).toBeInTheDocument();
  });

  it("marks the open step as pressed", () => {
    render(<PlanCard goal={goal} activeUri={link.deeplink} onOpen={() => {}} />);
    expect(screen.getByRole("button", { name: "Open Enable Touch sensitivity" })).toHaveAttribute("aria-pressed", "true");
  });
});
