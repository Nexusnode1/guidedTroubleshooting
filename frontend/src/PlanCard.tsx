import { CheckIcon, ExternalLinkIcon, WarningIcon } from "./icons";
import type { Action, ActionableDeeplink, Goal, ValidationDeeplink } from "./types";

type OpenHandler = (link: ActionableDeeplink, validation: ValidationDeeplink | null | undefined) => void;

interface PlanCardProps {
  goal: Goal;
  activeUri: string | null;
  onOpen: OpenHandler;
}

/** The slot at the end of a step group: an Open button for a real deeplink, or a plain,
 * non-interactive tag for a manual or critical step that has none. Manual/critical tags are
 * spans, not buttons -- they must never look or behave like something you can click. */
function ActionSlot({
  action,
  link,
  validation,
  activeUri,
  onOpen,
}: {
  action: Action;
  link: ActionableDeeplink | null | undefined;
  validation: ValidationDeeplink | null | undefined;
  activeUri: string | null;
  onOpen: OpenHandler;
}) {
  if (link) {
    return (
      <button
        type="button"
        className="open"
        aria-label={`Open ${link.message || action.actionName}`}
        aria-pressed={activeUri === link.deeplink}
        onClick={() => onOpen(link, validation)}
      >
        Open action <ExternalLinkIcon />
      </button>
    );
  }
  if (action.category === "critical") {
    return (
      <span className="tag tag--critical">
        <WarningIcon /> Critical step
      </span>
    );
  }
  return (
    <span className="tag tag--manual">
      <CheckIcon /> Manual step
    </span>
  );
}

function ActionItem({
  action,
  index,
  activeUri,
  onOpen,
}: {
  action: Action;
  index: number;
  activeUri: string | null;
  onOpen: OpenHandler;
}) {
  return (
    <li className="action">
      <div className="action__rail" aria-hidden="true">
        <span className={`action__step-no action__step-no--${action.category}`}>{index + 1}</span>
      </div>
      <div className={`action__card action__card--${action.category}`}>
        <header className="action__head">
          <div className="action__heading">
            <h4 className="action__name">{action.actionName}</h4>
            <p className="action__desc">{action.description}</p>
          </div>
          <span className={`badge badge--${action.category}`}>{action.category}</span>
        </header>
        {action.category === "critical" && (
          <p className="action__warn">
            <WarningIcon /> This step is disruptive. Back up your data first.
          </p>
        )}
        {action.stepGroups.map((group, groupIndex) => (
          <div className="group" key={groupIndex}>
            <ol className="steps">
              {group.steps.map((step, stepIndex) => (
                <li key={stepIndex}>{step}</li>
              ))}
            </ol>
            <ActionSlot
              action={action}
              link={group.actionableDeeplink}
              validation={group.validationDeeplink}
              activeUri={activeUri}
              onOpen={onOpen}
            />
          </div>
        ))}
      </div>
    </li>
  );
}

export function PlanCard({ goal, activeUri, onOpen }: PlanCardProps) {
  const confidence = Math.round(Math.max(0, Math.min(1, goal.score)) * 100);
  return (
    <article className="plan">
      <header className="plan__head">
        <div>
          <span className="plan__badge">
            <CheckIcon /> Verified troubleshooting
          </span>
          <h3 className="plan__title">{goal.title}</h3>
        </div>
        <span className="plan__score" title="How closely this matches your description">
          {confidence}% match
        </span>
      </header>
      <p className="plan__goal">{goal.goal}</p>
      <ol className="plan__actions">
        {goal.actions.map((action, index) => (
          <ActionItem
            key={`${index}-${action.actionName}`}
            action={action}
            index={index}
            activeUri={activeUri}
            onOpen={onOpen}
          />
        ))}
      </ol>
    </article>
  );
}
