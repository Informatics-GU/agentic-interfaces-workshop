import type { A2UIAction, A2UIComponent, A2UIOperation, A2UISurface } from './types';

/* -------------------------------------------------------------------------- */
/* Surface store helpers                                                      */
/* -------------------------------------------------------------------------- */

type Surfaces = Record<string, A2UISurface>;

export function applyOperation(surfaces: Surfaces, op: A2UIOperation): Surfaces {
  if (op.createSurface) {
    const { surfaceId, catalogId } = op.createSurface;
    return { ...surfaces, [surfaceId]: { surfaceId, catalogId, components: {}, data: {} } };
  }

  if (op.updateComponents) {
    const { surfaceId, components } = op.updateComponents;
    const surface = surfaces[surfaceId];
    if (!surface) return surfaces;
    return {
      ...surfaces,
      [surfaceId]: {
        ...surface,
        components: {
          ...surface.components,
          ...Object.fromEntries(components.map((component) => [component.id, component])),
        },
      },
    };
  }

  if (op.updateDataModel) {
    const { surfaceId, path = '/', value } = op.updateDataModel;
    const surface = surfaces[surfaceId];
    if (!surface) return surfaces;
    return {
      ...surfaces,
      [surfaceId]: { ...surface, data: setPath(surface.data, path, value) as Record<string, unknown> },
    };
  }

  if (op.deleteSurface) {
    const next = { ...surfaces };
    delete next[op.deleteSurface.surfaceId];
    return next;
  }

  return surfaces;
}

export function getPath(data: unknown, path: string): unknown {
  if (path === '/' || path === '') return data;
  return path
    .split('/')
    .filter(Boolean)
    .reduce<unknown>((acc, key) => (acc == null ? undefined : (acc as Record<string, unknown>)[key]), data);
}

export function setPath(data: unknown, path: string, value: unknown): unknown {
  if (path === '/' || path === '') return value;
  const keys = path.split('/').filter(Boolean);
  const root: Record<string, unknown> = { ...((data as Record<string, unknown>) ?? {}) };
  let cursor = root;
  keys.forEach((key, index) => {
    if (index === keys.length - 1) {
      cursor[key] = value;
    } else {
      const child = cursor[key];
      cursor[key] = Array.isArray(child) ? [...child] : { ...((child as Record<string, unknown>) ?? {}) };
      cursor = cursor[key] as Record<string, unknown>;
    }
  });
  return root;
}

function bindingPath(value: unknown): string | null {
  if (value && typeof value === 'object' && 'path' in value) {
    return String((value as { path: unknown }).path);
  }
  return null;
}

function resolve(value: unknown, data: unknown): unknown {
  const path = bindingPath(value);
  return path ? getPath(data, path) : value;
}

function isFilled(value: unknown): boolean {
  if (Array.isArray(value)) {
    return value.some((item) =>
      item && typeof item === 'object'
        ? String((item as Record<string, unknown>).name ?? '').trim().length > 0
        : String(item).trim().length > 0,
    );
  }
  if (typeof value === 'string') return value.trim().length > 0;
  return value != null;
}

/* -------------------------------------------------------------------------- */
/* Renderer                                                                   */
/* -------------------------------------------------------------------------- */

type Props = {
  surface: A2UISurface;
  onData: (surfaceId: string, path: string, value: unknown) => void;
  onAction: (action: A2UIAction) => void;
  disabled?: boolean;
};

type Ctx = {
  surface: A2UISurface;
  onData: (path: string, value: unknown) => void;
  onAction: (action: A2UIAction) => void;
  disabled: boolean;
};

export function A2UIRenderer({ surface, onData, onAction, disabled = false }: Props) {
  const root = surface.components['root'];
  if (!root) {
    return <div className="empty-state">Waiting for the agent…</div>;
  }

  const ctx: Ctx = {
    surface,
    onData: (path, value) => onData(surface.surfaceId, path, value),
    onAction,
    disabled,
  };
  const footer = surface.components['footer'];

  return (
    <>
      {renderComponent(root, ctx)}
      {footer ? renderComponent(footer, ctx) : null}
    </>
  );
}

function renderChildren(component: A2UIComponent, ctx: Ctx) {
  return (component.children ?? [])
    .map((id) => ctx.surface.components[id])
    .filter(Boolean)
    .map((child) => (
      <div className="a2ui-child" key={child.id}>
        {renderComponent(child, ctx)}
      </div>
    ));
}

function renderComponent(component: A2UIComponent, ctx: Ctx) {
  const children = renderChildren(component, ctx);

  switch (component.component) {
    /* ------------------------------ form ------------------------------ */
    case 'Form':
      return (
        <section className="a2ui-form">
          <div className="form-heading">
            <h3>{String(component.title ?? '')}</h3>
            {component.subtitle ? <p>{String(component.subtitle)}</p> : null}
          </div>
          {children}
        </section>
      );

    case 'Section':
      return (
        <div className="form-section">
          <header>
            <h4>{String(component.title ?? '')}</h4>
            {component.description ? <p>{String(component.description)}</p> : null}
          </header>
          <div className={`form-grid cols-${Number(component.columns ?? 1)}`}>{children}</div>
        </div>
      );

    case 'TextField': {
      const path = bindingPath(component.value);
      const value = String(resolve(component.value, ctx.surface.data) ?? '');
      const label = String(component.label ?? '');
      const placeholder = String(component.placeholder ?? '');
      const change = (next: string) => path && ctx.onData(path, next);
      return (
        <label className="field">
          <span>{label}</span>
          {component.multiline ? (
            <textarea
              rows={3}
              value={value}
              placeholder={placeholder}
              disabled={ctx.disabled}
              onChange={(e) => change(e.target.value)}
            />
          ) : (
            <input
              type={String(component.inputType ?? 'text')}
              value={value}
              placeholder={placeholder}
              disabled={ctx.disabled}
              onChange={(e) => change(e.target.value)}
            />
          )}
        </label>
      );
    }

    case 'AssignmentList':
      return <AssignmentList component={component} ctx={ctx} />;

    case 'ChoiceGroup':
      return <ChoiceGroup component={component} ctx={ctx} />;

    case 'ActionBar':
      return <div className="action-bar">{children}</div>;

    case 'Button': {
      const action = component.action as { event?: { name?: string } } | undefined;
      const eventName = action?.event?.name;
      const requires = Array.isArray(component.requires) ? component.requires.map(String) : [];
      const unmet = requires.some((path) => !isFilled(getPath(ctx.surface.data, path)));
      return (
        <button
          type="button"
          className={component.variant === 'secondary' ? 'secondary' : ''}
          disabled={ctx.disabled || unmet || !eventName}
          title={unmet ? 'Fill in the required fields first' : undefined}
          onClick={() =>
            eventName &&
            ctx.onAction({ name: eventName, surfaceId: ctx.surface.surfaceId, data: ctx.surface.data })
          }
        >
          {String(component.label ?? 'Continue')}
        </button>
      );
    }

    /* ----------------------------- schedule ---------------------------- */
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
          <div className="block-time">
            {String(component.start)}–{String(component.end)}
          </div>
          <strong>{String(component.assignment)}</strong>
          {component.course ? <span>{String(component.course)}</span> : null}
          <small>
            {String(component.minutes)} min · due {String(component.due)}
          </small>
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
          <span>{Math.round((Number(component.totalMinutes ?? 0) / 60) * 10) / 10} scheduled hours</span>
        </div>
      );

    case 'WarningBanner':
      return (
        <div className={`warning-banner ${String(component.severity ?? 'warning')}`}>
          {String(component.message)}
        </div>
      );

    default:
      return <div className="unknown-component">Unknown catalog component: {component.component}</div>;
  }
}

/* -------------------------------------------------------------------------- */
/* Composite inputs                                                           */
/* -------------------------------------------------------------------------- */

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

type Assignment = { name: string; course: string; dueDay: string; dueTime: string; hours: number };

const blankAssignment = (): Assignment => ({
  name: '',
  course: '',
  dueDay: 'Friday',
  dueTime: '23:59',
  hours: 1,
});

function AssignmentList({ component, ctx }: { component: A2UIComponent; ctx: Ctx }) {
  const path = bindingPath(component.value);
  const current = resolve(component.value, ctx.surface.data);
  const rows: Assignment[] = Array.isArray(current) ? (current as Assignment[]) : [];

  const write = (next: Assignment[]) => path && ctx.onData(path, next);
  const patch = (index: number, change: Partial<Assignment>) =>
    write(rows.map((row, i) => (i === index ? { ...row, ...change } : row)));

  return (
    <div className="assignment-list">
      {rows.map((row, index) => (
        <div className="assignment-row" key={index}>
          <label className="field">
            <span>Assignment</span>
            <input
              value={row.name}
              placeholder="Physics homework"
              disabled={ctx.disabled}
              onChange={(e) => patch(index, { name: e.target.value })}
            />
          </label>
          <label className="field">
            <span>Course</span>
            <input
              value={row.course}
              placeholder="PHYS 101"
              disabled={ctx.disabled}
              onChange={(e) => patch(index, { course: e.target.value })}
            />
          </label>
          <label className="field">
            <span>Due day</span>
            <select
              value={row.dueDay}
              disabled={ctx.disabled}
              onChange={(e) => patch(index, { dueDay: e.target.value })}
            >
              {DAY_NAMES.map((day) => (
                <option key={day}>{day}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Due time</span>
            <input
              type="time"
              value={row.dueTime}
              disabled={ctx.disabled}
              onChange={(e) => patch(index, { dueTime: e.target.value })}
            />
          </label>
          <label className="field">
            <span>Hours</span>
            <input
              type="number"
              min={0.25}
              step={0.25}
              value={row.hours}
              disabled={ctx.disabled}
              onChange={(e) => patch(index, { hours: Number(e.target.value) })}
            />
          </label>
          <button
            type="button"
            className="ghost"
            aria-label={`Remove assignment ${index + 1}`}
            disabled={ctx.disabled || rows.length === 1}
            onClick={() => write(rows.filter((_, i) => i !== index))}
          >
            Remove
          </button>
        </div>
      ))}
      <div>
        <button
          type="button"
          className="secondary"
          disabled={ctx.disabled}
          onClick={() => write([...rows, blankAssignment()])}
        >
          Add assignment
        </button>
      </div>
    </div>
  );
}

function ChoiceGroup({ component, ctx }: { component: A2UIComponent; ctx: Ctx }) {
  const path = bindingPath(component.value);
  const multi = component.mode === 'multi';
  const current = resolve(component.value, ctx.surface.data);
  const selected: string[] = multi
    ? Array.isArray(current)
      ? current.map(String)
      : []
    : current != null && current !== ''
      ? [String(current)]
      : [];

  const options = (component.children ?? [])
    .map((id) => ctx.surface.components[id])
    .filter((child): child is A2UIComponent => Boolean(child) && child.component === 'OptionCard');

  const toggle = (optionId: string) => {
    if (!path) return;
    if (!multi) return ctx.onData(path, optionId);
    ctx.onData(
      path,
      selected.includes(optionId) ? selected.filter((id) => id !== optionId) : [...selected, optionId],
    );
  };

  return (
    <div className="choice-group" role={multi ? 'group' : 'radiogroup'}>
      {component.label ? <span className="choice-label">{String(component.label)}</span> : null}
      <div className="option-grid">
        {options.map((option) => {
          const optionId = String(option.optionId);
          const on = selected.includes(optionId);
          return (
            <button
              type="button"
              key={option.id}
              className={`option-card ${on ? 'selected' : ''}`}
              aria-pressed={on}
              disabled={ctx.disabled}
              onClick={() => toggle(optionId)}
            >
              <span className="option-title">
                <strong>{String(option.label)}</strong>
                {option.badge ? <em className="badge">{String(option.badge)}</em> : null}
              </span>
              {option.meta ? <span className="option-meta">{String(option.meta)}</span> : null}
              {option.description ? <small>{String(option.description)}</small> : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}