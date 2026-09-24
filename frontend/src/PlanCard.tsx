import type { Action, ActionableDeeplink, Goal, ValidationDeeplink } from "./types";

type OpenHandler = (link: ActionableDeeplink, validation: ValidationDeeplink | null | undefined) => void;

interface PlanCardProps {
  goal: Goal;
  activeUri: string | null;
  onOpen: OpenHandler;
}

function ActionItem({ action, activeUri, onOpen }: { action: Action; activeUri: string | null; onOpen: OpenHandler }) {
  return (
    <li className={`action action--${action.category}`}>
      <header className="action__head">
        <span className={`badge badge--${action.category}`}>{action.category}</span>
        <h4 className="action__name">{action.actionName}</h4>
      </header>
      <p className="action__desc">{action.description}</p>
      {action.category === "critical" && (
        <p className="action__warn">This step is disruptive. Back up your data first.</p>
      )}
      {action.stepGroups.map((group, index) => {
        const link = group.actionableDeeplink;
        return (
          <div className="group" key={index}>
            <ol className="steps">
              {group.steps.map((step, stepIndex) => (
                <li key={stepIndex}>{step}</li>
              ))}
            </ol>
            {link && (
              <button
                type="button"
                className="open"
                aria-label={`Open ${link.message || action.actionName}`}
                aria-pressed={activeUri === link.deeplink}
                onClick={() => onOpen(link, group.validationDeeplink)}
              >
                Open
              </button>
            )}
          </div>
        );
      })}
    </li>
  );
}

export function PlanCard({ goal, activeUri, onOpen }: PlanCardProps) {
  return (
    <article className="plan">
      <h3 className="plan__goal">{goal.goal}</h3>
      <ol className="plan__actions">
        {goal.actions.map((action, index) => (
          <ActionItem key={`${index}-${action.actionName}`} action={action} activeUri={activeUri} onOpen={onOpen} />
        ))}
      </ol>
    </article>
  );
}
