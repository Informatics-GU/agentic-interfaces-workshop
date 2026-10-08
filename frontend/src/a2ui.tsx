import type { A2UIComponent } from './types';

type Props = {
  components: Record<string, A2UIComponent>;
  rootId?: string;
};

export function A2UIRenderer({ components, rootId = 'root' }: Props) {
  const root = components[rootId];
  if (!root) {
    return <div className="empty-state">The A2UI week schedule will render here.</div>;
  }

  return <>{renderComponent(root, components)}</>;
}

function renderComponent(component: A2UIComponent, all: Record<string, A2UIComponent>) {
  const children = (component.children ?? [])
    .map((id) => all[id])
    .filter(Boolean)
    .map((child) => <div key={child.id}>{renderComponent(child, all)}</div>);

  switch (component.component) {
    case 'WeekSchedule':
      return (
        <section className="week-schedule">
          <div className="schedule-heading">
            <h2>{String(component.title ?? 'Week Schedule')}</h2>
            {component.subtitle ? <p>{String(component.subtitle)}</p> : null}
          </div>
          <div className="week-grid">{children}</div>
        </section>
      );

    case 'DayColumn':
      return (
        <article className="day-column">
          <header>
            <strong>{String(component.day ?? '')}</strong>
            {component.date ? <span>{String(component.date)}</span> : null}
          </header>
          <div className="day-body">{children.length ? children : <em>No study blocks</em>}</div>
        </article>
      );

    case 'StudyBlock':
      return (
        <div className={`study-block priority-${String(component.priority ?? 'medium')}`}>
          <div className="block-time">{String(component.start)}–{String(component.end)}</div>
          <strong>{String(component.assignment)}</strong>
          {component.course ? <span>{String(component.course)}</span> : null}
          <small>{String(component.minutes)} min · due {String(component.due)}</small>
          {component.note ? <small>{String(component.note)}</small> : null}
        </div>
      );

    case 'DeadlineBadge':
      return (
        <div className={`deadline ${String(component.urgency ?? 'normal')}`}>
          <strong>{String(component.label)}</strong>
          <span>{String(component.due)}</span>
        </div>
      );

    case 'ScheduleSummary':
      return (
        <div className="schedule-summary">
          <strong>Plan summary</strong>
          <p>{String(component.text)}</p>
          <span>{Math.round(Number(component.totalMinutes ?? 0) / 60 * 10) / 10} scheduled hours</span>
        </div>
      );

    case 'WarningBanner':
      return <div className={`warning-banner ${String(component.severity ?? 'warning')}`}>{String(component.message)}</div>;

    default:
      return <div className="unknown-component">Unknown catalog component: {component.component}</div>;
  }
}
