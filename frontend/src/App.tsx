import { useEffect, useRef, useState } from 'react';
import { A2UIRenderer, applyOperation, setPath } from './a2ui';
import { streamAgUi } from './agui';
import type { A2UIAction, A2UIOperation, A2UISurface, AgEvent, ChatMessage } from './types';

const CLASSIC_16 = [
  'RUN_STARTED', 'RUN_FINISHED', 'RUN_ERROR', 'STEP_STARTED', 'STEP_FINISHED',
  'TEXT_MESSAGE_START', 'TEXT_MESSAGE_CONTENT', 'TEXT_MESSAGE_END',
  'TOOL_CALL_START', 'TOOL_CALL_ARGS', 'TOOL_CALL_END', 'TOOL_CALL_RESULT',
  'STATE_SNAPSHOT', 'STATE_DELTA', 'MESSAGES_SNAPSHOT', 'CUSTOM',
];

const STEPS = [
  { surfaceId: 'intake', label: 'Your week' },
  { surfaceId: 'preferences', label: 'Study times' },
  { surfaceId: 'week-schedule', label: 'Your plan' },
];

const SURFACE_TITLES: Record<string, string> = {
  intake: 'Your week',
  preferences: 'Study preferences',
  'week-schedule': 'Your week plan',
};

// What shows up in the chat when the student clicks a button.
const ACTION_CHAT: Record<string, string> = {
  submit_schedule: 'Here is my week and my assignments.',
  back_to_schedule: 'I want to edit my schedule.',
  submit_preferences: 'These are my study preferences.',
  back_to_preferences: 'I want to change my study times.',
};

export function App() {
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [events, setEvents] = useState<AgEvent[]>([]);
  const [surfaces, setSurfaces] = useState<Record<string, A2UISurface>>({});
  const [busy, setBusy] = useState(false);

  // Agent state round-trips through AG-UI: the server emits STATE_SNAPSHOT, we send it back next run.
  const agentState = useRef<Record<string, unknown>>({});
  const threadId = useRef(crypto.randomUUID());
  const started = useRef(false);

  const seen = new Set(events.map((event) => event.type));

  function consume(event: AgEvent) {
    setEvents((prev) => [...prev, event]);

    switch (event.type) {
      case 'TEXT_MESSAGE_START':
        setChat((prev) => [...prev, { role: 'assistant', content: '' }]);
        break;

      case 'TEXT_MESSAGE_CONTENT':
        setChat((prev) => {
          const copy = [...prev];
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].role === 'assistant') {
              copy[i] = { ...copy[i], content: copy[i].content + String(event.delta ?? '') };
              break;
            }
          }
          return copy;
        });
        break;

      case 'STATE_SNAPSHOT': {
        // Only keep planner state (the demo endpoint's snapshot has no "phase").
        const snapshot = event.snapshot as Record<string, unknown> | undefined;
        if (snapshot && 'phase' in snapshot) agentState.current = snapshot;
        break;
      }

      case 'CUSTOM':
        if (event.name === 'a2ui') {
          setSurfaces((prev) => applyOperation(prev, event.value as A2UIOperation));
        }
        break;
    }
  }

  async function runAction(name: string, data: Record<string, unknown> = {}, userText?: string) {
    if (busy) return;
    setBusy(true);
    setEvents([]);

    if (name === 'start' || name === 'restart') {
      agentState.current = {};
      setChat([]);
    }
    if (userText) setChat((prev) => [...prev, { role: 'user', content: userText }]);

    try {
      await streamAgUi(
        '/agent',
        [{ id: crypto.randomUUID(), role: 'user', content: userText ?? 'Start the study planner.' }],
        consume,
        {
          threadId: threadId.current,
          state: agentState.current,
          forwardedProps: { a2uiAction: { name, data } },
        },
      );
    } catch (error) {
      consume({ type: 'CLIENT_ERROR', message: String(error) });
    } finally {
      setBusy(false);
    }
  }

  // Show the intake form as soon as the app loads.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void runAction('start');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleAction(action: A2UIAction) {
    void runAction(action.name, action.data, ACTION_CHAT[action.name]);
  }

  function handleData(surfaceId: string, path: string, value: unknown) {
    setSurfaces((prev) => {
      const surface = prev[surfaceId];
      if (!surface) return prev;
      return { ...prev, [surfaceId]: { ...surface, data: setPath(surface.data, path, value) as Record<string, unknown> } };
    });
  }

  async function demoEvents() {
    if (busy) return;
    setBusy(true);
    setEvents([]);
    try {
      const message = 'Demonstrate the classic event catalogue.';
      const messages = [{ id: crypto.randomUUID(), role: 'user' as const, content: message }];
      await streamAgUi('/demo-events?terminal=finished', messages, consume);
      await streamAgUi('/demo-events?terminal=error', messages, consume);
    } catch (error) {
      consume({ type: 'CLIENT_ERROR', message: String(error) });
    } finally {
      setBusy(false);
    }
  }

  const errors = events.filter((e) => e.type === 'RUN_ERROR' || e.type === 'CLIENT_ERROR');
  const lastError = errors.length ? String(errors[errors.length - 1].message ?? 'Something went wrong.') : null;
  const surfaceList = Object.values(surfaces);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">AG-UI 1.0 transport · A2UI declarative form and schedule</p>
          <h1>Study Planner Agent</h1>
        </div>
        <div className="topbar-actions">
          <button className="secondary" onClick={() => void runAction('restart')} disabled={busy}>Start over</button>
          <button className="secondary" onClick={demoEvents} disabled={busy}>Demonstrate classic 16</button>
        </div>
      </header>

      <ol className="stepper" aria-label="Progress">
        {STEPS.map((step) => (
          <li key={step.surfaceId} className={surfaces[step.surfaceId] ? 'active' : ''}>
            {step.label}
          </li>
        ))}
      </ol>

      <section className="workspace">
        <div className="left-stack">
          {busy ? <div className="busy-bar" role="status">The agent is working…</div> : null}
          {lastError && !busy ? <div className="error-bar" role="alert">{lastError}</div> : null}

          {surfaceList.map((surface) => (
            <section className="panel surface-panel" key={surface.surfaceId}>
              <div className="panel-title">
                <h2>{SURFACE_TITLES[surface.surfaceId] ?? surface.surfaceId}</h2>
                <span>A2UI surface: {surface.surfaceId}</span>
              </div>
              <A2UIRenderer surface={surface} onData={handleData} onAction={handleAction} disabled={busy} />
            </section>
          ))}

          {surfaceList.length === 0 ? (
            <section className="panel">
              <div className="empty-state">{busy ? 'Getting your form ready…' : 'No surface yet. Press Start over.'}</div>
            </section>
          ) : null}

          <section className="panel chat-panel">
            <div className="panel-title"><h2>Chat</h2><span>TEXT_MESSAGE_* renders here</span></div>
            <div className="chat-log">
              {chat.length === 0 ? <div className="empty-state">The agent's messages will appear here.</div> : null}
              {chat.map((message, i) => (
                <div className={`bubble ${message.role}`} key={i}>
                  <small>{message.role}</small>
                  <p>{message.content}</p>
                </div>
              ))}
            </div>
          </section>
        </div>

        <aside className="panel event-panel">
          <div className="panel-title sticky">
            <div>
              <h2>AG-UI event stream</h2>
              <span>{events.length} received · {CLASSIC_16.filter((type) => seen.has(type)).length}/16 classic types seen</span>
            </div>
            <button className="ghost" onClick={() => setEvents([])}>Clear</button>
          </div>

          <div className="event-catalogue">
            {CLASSIC_16.map((type) => <span key={type} className={seen.has(type) ? 'seen' : ''}>{type}</span>)}
          </div>
          <p className="catalogue-note">This panel intentionally tracks the classic 16 requested for the demo. Current AG-UI also defines newer event families.</p>

          <div className="event-list">
            {events.map((event, i) => (
              <details className="event-card" key={`${i}-${event.type}`} open={i === events.length - 1}>
                <summary><b>{String(i + 1).padStart(3, '0')}</b><span>{event.type}</span></summary>
                <pre>{JSON.stringify(event, null, 2)}</pre>
              </details>
            ))}
          </div>
        </aside>
      </section>
    </main>
  );
}